
from wafer_device import Wafer_Device 
from comp_graph import CompGraph
import pipeline as pipe
from ML import *
import simpy
import math

if __name__ == '__main__':
    
    #1.define simpy environment
    env=simpy.Environment()

    #2.set hardware parameters
    wd=Wafer_Device(
        env=env,
        tile_inter_shape=[16,4],
        tile_intra_shape=[4,4],
        tile_intra_noc_bw_GB=1024,
        tile_inter_noc_bw_GB=1024*0.6,
        tile_dram_bw_GB=12288/16/8,
        tile_dram_capacity_GB=6/16,
        edge_die_dram_bw_GB=512,
        clk_freq_Ghz=1,
        with_3ddram_per_tile=True
        )
    
    #read ml compute graph from json file or define ml compute graph by yourself
    gp=CompGraph.gread(path='mljson',name='gpt-3.json')
    batch_size=gp.root.param_dim[0]
    #print(batch_size)

    #3.mapping by hand
    #TODO mapping with graph arch info
    tiles_id=wd.device_list() 
    STG_NUM=16
    DATA_PARALLELISM=2
    tiles=[]
    for i in range(STG_NUM):  
        tiles.append(tiles_id[i::STG_NUM])
    Layers_num=len(gp)
    nums_per_stg=math.ceil(Layers_num/STG_NUM)

    j=0
    ops=[]
    ops_per_stg=[]
    for i,op_name in enumerate(gp.op_dict):
        d_size=len(tiles[j])
        dp=DATA_PARALLELISM
        mp=d_size//dp
        #make sure that product of model parallelism and data parallelism is equal to numbers of device 
        assert(mp*dp==d_size)
        op=gp.op_dict[op_name]
        op.dpmap(device_id=tiles[j],p_sgy=[dp,mp])
        ops.append(op)
        if i % nums_per_stg==nums_per_stg-1:
            j+=1
            ops_per_stg.append(ops)
            ops=[]
    if ops!=[]:
        ops_per_stg[-1].append(op)
    #write graph with device to file
    #CompGraph.gwrite(gp,path='mljson',name='gpt_dp_test.json')

    #4.pipeline define and set
    stgs=[]
    for i in range(STG_NUM):
        last_core_id=None if i==0 else tiles[i-1]
        cur_core_id=tiles[i]
        next_core_id=None if i==STG_NUM-1 else tiles[i+1]
        stgs.append(pipe.Stage(env,ops_per_stg[i],last_core_id,cur_core_id,next_core_id,noc=wd))
    #micro_batch=batch_size//STG_NUM
    micro_batch=batch_size//10

    stages=pipe.Stages(
        env=env,
        mini_batch_size=batch_size,
        micro_batch_size=micro_batch,#TODO
        stages=stgs,
        noc=wd
        )
    stages.pipeline_set(boost_mode=True)



    #5.simpy run  
    one_weeks_ms=24*60*60*7*1000
    scale_sim_time=one_weeks_ms*1000
    stages.simpy_run(until=scale_sim_time)

    #6. log and info output
    stages.pipeline_status()
    #res_type='edge_dram' or '3dram' or 'noc'
    wd.resource_visualize(res_type='edge_dram')








