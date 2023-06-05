import ML
from util import *
from typing import List,Optional,Union
class CompOp():
    def __init__(self,op_type:ML.OP,op_param:List[int],parallel_strategy:List[int]=[1,1]) -> None:
        #base info 
        self.type=op_type
        self.param_dim=op_param
        self.p_sgy=parallel_strategy
        self.ZeRO=ML.ZeRO_strategy.none
        self.o_shape=[]
        self.i_shape=[]
        #only for complex op like transformer @fangjh21.202306602
        #influenced by parallism strategy
        #capacity req
        self.intra_act_size_m=0 
        self.w_s_g_size_m=[0,0,0]
        #bandwidth req
        self.intra_act_access_m=0
        self.w_s_g_access_m=[0,0,0]
        #compute power req
        self.fd_macs=0  
  
        self.__analysis()
    def __str__(self):
        return '({},{})'.format(self.type,self.param_dim)
    def __analysis(self):
        if self.type==ML.OP.Linear:
            assert(len(self.param_dim)==4 and len(self.p_sgy)==4)#B,M,N,K
            [B,M,N,K]=self.param_dim
            [Nd,Nm1,Nm2,Nm3]=self.p_sgy
            self.o_shape=[B//Nd,M//Nm1,N//Nm2] #[B,M,N]
            self.i_shape=[B//Nd,N//Nm2,K//Nm3] #[B,K,N]  
            
            #capacity req
            self.intra_act_size_m=0 
            self.w_s_g_size_m=[(M*K+M)/Nm1/Nm2/Nm3/1000/1000,2*(M*K+M)/Nm1/Nm2/Nm3/1000/1000,(M*K+M)/Nm1/Nm2/Nm3/1000/1000]
            #bandwidth req
            self.intra_act_access_m=0
            self.w_s_g_access_m=[0,0,0]
            #compute power req
            self.fd_macs=B*M*N*K/Nd/Nm1/Nm2/Nm3
        elif self.type==ML.OP.Conv2:
            #TODO
            assert(len(self.param_dim)==7)#B,C,H,W,R,S,K
            [B,C,H,W,R,S,K]=self.param_dim
            o_h=H - R  + 1
            o_w=W - S  + 1
            self.o_shape=[B,K,o_h,o_w]
            self.i_shape=[B,C,H,W]
            #capacity req
            self.intra_act_size_m=0 
            self.w_s_g_size_m=[(R*S*C+1)*K/1000/1000,2*(R*S*C+1)*K/1000/1000,(R*S*C+1)*K/1000/1000]
            #bandwidth req
            self.intra_act_access_m=0
            self.w_s_g_access_m=[0,0,0]
            #compute power req
            self.fd_macs=C*R*S*o_h*o_w*K
        elif self.type==ML.OP.Transformer:
            #TODO for verification with hand analysis
            assert(len(self.param_dim)==4 and len(self.p_sgy)==2)
            [B,S,H,A]=self.param_dim
            [Nd,Nm]=self.p_sgy
            self.o_shape=[B//Nd,S,H]
            self.i_shape=[B//Nd,S,H]  

            #reference:Wang huizheng's
            if self.ZeRO==ML.ZeRO_strategy.ZeRO_3:
                w=12*H*H/Nm/Nd
                w_c=12*H*H/Nm #TODO
            else:
                w=12*H*H/Nm
                w_c=12*H*H/Nm #TODO
            if self.ZeRO!=ML.ZeRO_strategy.none:
                s=3*12*H*H/Nm/Nd
                s_c=3*12*H*H/Nm/Nd 
            else:
                s=3*12*H*H/Nm
                s_c=3*12*H*H/Nm #TODO
            if self.ZeRO==ML.ZeRO_strategy.ZeRO_3 or self.ZeRO==ML.ZeRO_strategy.ZeRO_2 :
                g=12*H*H/Nm/Nd
                g_c=12*H*H/Nm #TODO
            else:
                g=12*H*H/Nm
                g_c=12*H*H/Nm #TODO
            self.w_s_g_size_m=[w,s,g]#capacity req
            self.w_s_g_access_m=[w_c,s_c,g_c]#bandwidth req
            self.intra_act_size_m=B*S*((15*H+2.5*A*S)/Nm+2*H)/Nd
            self.intra_act_access_m=((34*B*S*H+7*B*A*S*S)/Nm+4*B*S*H)/Nd#bandwidth req
            self.fd_macs=(24*B*S*H*H+4*B*S*S*H)/Nd/Nm#compute power req
  
        elif self.type==ML.OP.Embedding:
            #TODO
            assert(len(self.param_dim)==4)
            self.o_shape=0 
            self.i_shape=0 
            self.fd_macs=0
        else:
            #TODO
            self.o_shape=0 
            self.i_shape=0 
            self.fd_macs=0
            raise NotImplementedError
    def set_ZeRO(self,ZeRO):
        self.ZeRO=ZeRO
        self.__analysis()

class CommOp():
    def __init__(self,device_id:Optional[List[int]]=None,comm_type:ML.COMM=ML.COMM.NONE,comm_size=0) -> None:
        self.type=comm_type
        self.size=comm_size
        self.device=device_id
        self.__analysis()
    def __analysis(self):
        assert(self.type==ML.COMM.NONE or self.type==ML.COMM.ALL_REDUCE or self.type==ML.COMM.ALL_2_ALL)
    def __str__(self) -> str:
        return '({},{})'.format(self.type,self.size)
    def No_comm(self):
        if self.type==ML.COMM.NONE or self.size==0:
            return True
        else:
            return False       
class Oppd(CompOp):
    def __init__(self,op_type:ML.OP,op_param:List[int],hint_name:str) -> None:
        super(Oppd,self).__init__(op_type,op_param)
        self.hint_name=hint_name
        self.device=[]
        #parallism_dim:forward(f):(comm_type,comm_size_MB),backward(b):updata_weight(u):
        #here is a fact that communication caused by data parallelism only happens on weight update phase,
        #similarly,communication caused by model parallelism only happens on forward and backward phase
        self.f_b_u_comm=[0,0,0]
        self.ZeRO_comm=[0,0] #forward all-gather,backward all-gather
        self.dpmap_flag=False
    def dpmap(self,device_id:List[int],parallel_strategy:Optional[List[int]]=None):
        assert parallel_strategy==None or len(parallel_strategy)<=4,'The number of parallel dimensions exceeds the op dim space!'
        if (parallel_strategy==None or parallel_strategy==[]):
            #print('Warning:parallel dimension not specified as the number of device  more than one!')
            self.p_sgy=[1,len(device_id)]
            self.device=device_id
        else:
            assert(mbytes(parallel_strategy)==len(device_id))
            self.p_sgy=parallel_strategy
            self.device=device_id
        # TODO 完成并行通信算子的生成
        self.comm_insert()
        self.dpmap_flag=True
        return True
    def comm_insert(self):
        #pass
        self.__analysis()
        if self.type==ML.OP.Transformer:
            [B,S,H,A]=self.param_dim
            [Nd,Nm]=self.p_sgy

            #Nd:
            Nd_Group=self.device[::Nm]
            Nm_Group=[]
            comm_info=[]
            comm_info.append(CommOp(ML.COMM.ALL_2_ALL,self.w_s_g_size_m[0]))#forward
            comm_info.append(CommOp(ML.COMM.ALL_2_ALL,self.w_s_g_size_m[0]))#backward
            comm_info.append(CommOp(ML.COMM.ALL_2_ALL,self.w_s_g_size_m[0]))#weight update
            self.f_b_u_comm.append(comm_info)
    def __str__(self):
        if self.dpmap_flag:
            return '{}:(({},{}),parallel_strategy={},device={})'.format(self.hint_name,self.type,self.param_dim,self.parallel_strategy,self.device)
        else:
            return '{}:({},{})'.format(self.hint_name,self.type,self.param_dim)
if __name__ == '__main__':
    op1=Oppd(op_type=ML.OP.Linear,op_param=[1,128,128,512],hint_name='s0')
    op1.dpmap(parallel_strategy=[0,1],device_id=[0,1])
    print(op1)