import pickle
import numpy as np
import scipy.sparse as sp
from scipy.sparse import csr_matrix, coo_matrix, dok_matrix
from math import ceil
import datetime
import random
import pandas as pd
import os
import scipy.io
import dgl
from tqdm import tqdm
import scipy.sparse as sp
from scipy.sparse import *
import torch
import torch.utils.data as dataloader

from data_utils.datasets_multi_behavior import CMLData, MMCLRData, AllRankTestData, MMCLRNeighborSampler
from config.configurator import configs



class DataHandlerCML:
    def __init__(self):
        if configs['data']['name'] == 'ijcai_15':
            predir = './datasets/ijcai_15/'
            self.behaviors = ['click','fav', 'cart', 'buy']
        elif configs['data']['name'] == 'tmall':
            predir = './datasets/tmall/'
            self.behaviors_SSL = ['pv','fav', 'cart', 'buy']
        elif configs['data']['name'] == 'retail_rocket':
            predir = './datasets/retail_rocket/'
            self.behaviors = ['view','cart', 'buy']

        self.train_file = predir + 'train_mat_'  # train_mat_buy.pkl 
        self.val_file = predir + 'test_mat.pkl'
        self.test_file = predir + 'test_mat.pkl'
        self.meta_multi_single_file = predir + 'meta_multi_single_beh_user_index_shuffle'


    def _load_data(self):
        self.meta_multi_single = pickle.load(open(self.meta_multi_single_file, 'rb'))

        self.t_max = -1 
        self.t_min = 0x7FFFFFFF
        self.time_number = -1
 
        self.user_num = -1
        self.item_num = -1
        self.behavior_mats = {} 
        self.behaviors_data = {}
        for i in range(0, len(self.behaviors)):
            with open(self.train_file + self.behaviors[i] + '.pkl', 'rb') as fs:  
                data = pickle.load(fs)
                self.behaviors_data[i] = data 

                if data.get_shape()[0] > self.user_num:  
                    self.user_num = data.get_shape()[0]  
                if data.get_shape()[1] > self.item_num:  
                    self.item_num = data.get_shape()[1]  

                if data.data.max() > self.t_max:
                    self.t_max = data.data.max()
                if data.data.min() < self.t_min:
                    self.t_min = data.data.min()

                if self.behaviors[i] == configs['model']['target']:
                    self.train_mat = data  
                    self.trainLabel = 1*(self.train_mat != 0)  
                    self.labelP = np.squeeze(np.array(np.sum(self.trainLabel, axis=0)))  

        self.test_mat = pickle.load(open(self.test_file, 'rb'))

        self.userNum = self.behaviors_data[0].shape[0]
        self.itemNum = self.behaviors_data[0].shape[1]
        # self.behavior = None
        self._data2mat()

    def _data2mat(self):
        time = datetime.datetime.now()
        print("Start building:  ", time)
        for i in range(0, len(self.behaviors_data)):
            self.behavior_mats[i] = self._get_use(self.behaviors_data[i])                  
        time = datetime.datetime.now()
        print("End building:", time)


    def _get_use(self, behaviors_data):
        behavior_mats = {}
        behaviors_data = (behaviors_data != 0) * 1
        behavior_mats['A'] = self._matrix_to_tensor(self._normalize_adj(behaviors_data))
        behavior_mats['AT'] = self._matrix_to_tensor(self._normalize_adj(behaviors_data.T))
        behavior_mats['A_ori'] = None

        return behavior_mats


    def _normalize_adj(self, adj):
        """Symmetrically normalize adjacency matrix."""
        adj = sp.coo_matrix(adj)
        rowsum = np.array(adj.sum(1))
        rowsum_diag = sp.diags(np.power(rowsum+1e-8, -0.5).flatten())

        colsum = np.array(adj.sum(0))
        colsum_diag = sp.diags(np.power(colsum+1e-8, -0.5).flatten())
        # return adj
        return rowsum_diag*adj
        # return adj*colsum_diag


    def _matrix_to_tensor(self, cur_matrix):
        if type(cur_matrix) != sp.coo_matrix:
            cur_matrix = cur_matrix.tocoo()  
        indices = torch.from_numpy(np.vstack((cur_matrix.row, cur_matrix.col)).astype(np.int64))  
        values = torch.from_numpy(cur_matrix.data)  
        shape = torch.Size(cur_matrix.shape)

        return torch.sparse.FloatTensor(indices, values, shape).to(torch.float32).cuda()  

    def load_data(self):  
        self._load_data()
        configs['data']['user_num'], configs['data']['item_num'] = self.train_mat.shape
        test_data = AllRankTestData(self.test_mat, self.train_mat)
        # self.torch_adj = self._make_torch_adj(self.train_mat)  # TODO
        train_u, train_v = self.train_mat.nonzero()
        train_data = np.hstack((train_u.reshape(-1,1), train_v.reshape(-1,1))).tolist()
        train_dataset = CMLData(self.behaviors, train_data, self.item_num, self.behaviors_data, True)
        self.train_dataloader = dataloader.DataLoader(train_dataset, batch_size=configs['train']['batch_size'], shuffle=True, num_workers=4, pin_memory=True)
        self.test_dataloader = dataloader.DataLoader(test_data, batch_size=configs['test']['batch_size'], shuffle=False, num_workers=0)



class DataHandlerMMCLR:
    def __init__(self):
        if configs['data']['name'] == 'tima':
            predir = './datasets/tima/'
            self.train_file_seq = predir + 'train_seq'
            self.train_file_graph = predir + 'traingraph.dgl'
            self.test_file_graph = predir + 'testgraph.dgl'
            self.train_file = predir + 'train_mat.pkl'
            self.test_file = predir + 'test_mat.pkl'

    def _load_data(self):      
        self.train_graph,self.item_ids,self.item_set=self._get_TIMA_Fllow_He(self.train_file_graph)
        self.test_graph,self.item_ids,self.item_set=self._get_TIMA_Fllow_He(self.test_file_graph)
        # return train_graph,test_graph,item_ids,item_set
        self.g=self.train_graph.to(configs['train']['device'])
        self.test_g=self.test_graph.to(configs['train']['device'])
        configs['model']['item_ids'] = self.item_ids
        configs['model']['item_set'] = self.item_set
        self.train_mat = pickle.load(open(self.train_file, 'rb'))
        self.test_mat = pickle.load(open(self.test_file, 'rb'))



    def _get_TIMA_Fllow_He(self, file):
        ## floow the create dataset method of He Xiangnan
        graph=dgl.load_graphs(file)
        graph=graph[0][0]
        test_set=dgl.data.utils.load_info(file+'.info')['testSet']
        for etype in ['buy','click','cart']:
            graph.nodes['item'].data[etype+'_dg']=graph.in_degrees(v='__ALL__',etype=etype)
            graph.nodes['user'].data[etype+'_dg']=graph.out_degrees(u='__ALL__',etype=etype)
        graph.nodes['item'].data['dg']=graph.in_degrees(v='__ALL__',etype='buy')+graph.in_degrees(v='__ALL__',etype='cart')+graph.in_degrees(v='__ALL__',etype='click')
        graph.nodes['user'].data['dg']=graph.out_degrees(u='__ALL__',etype='buy')+graph.out_degrees(u='__ALL__',etype='cart')+graph.out_degrees(u='__ALL__',etype='click')
    
        _,i=graph.edges(etype='buy')
        i=i.unique()
        in_dg=graph.in_degrees(i,etype='buy')
        i=i[in_dg>=1]
        item_ids=i.tolist()
        item_set=set(item_ids)
        return graph,item_ids,item_set
    
    def load_data(self):  
        self._load_data()
        train_dataset=MMCLRData(root_dir=self.train_file_seq)        
        train_sampler=MMCLRNeighborSampler(self.train_graph, num_layers=configs['model']['n_gcn_layers'])
        # train_sampler=NeighborSamplerForMGIR(train_graph, num_layers=configs['model']['n_gcn_layers'],args=args)
        # print(len(train_dataset))
        self.train_dataloader=dataloader.DataLoader(train_dataset,batch_size=configs['model']['batch_size'],collate_fn=train_sampler.sample_from_item_pairs
        ,shuffle=True,num_workers=8)
        eval_sampler=MMCLRNeighborSampler(self.train_graph, num_layers=configs['model']['n_gcn_layers'], neg_sample_num=configs['train']['neg_sample_num'],is_eval=True)
        # eval_sampler=NeighborSamplerForMGIR(train_graph, num_layers=configs['model']['n_gcn_layers'], args=args,neg_sample_num=configs['train']['neg_sample_num'],is_eval=True)
        vaild_dataset=MMCLRData(root_dir=self.train_file_seq,eval='test',neg_sample_num=configs['train']['neg_sample_num'])
        vaild_dataloader=dataloader.DataLoader(vaild_dataset,batch_size=256,collate_fn=eval_sampler.sample_from_item_pairs,shuffle=True,num_workers=8)
        test_dataset=MMCLRData(root_dir=self.train_file_seq,eval='test',neg_sample_num=configs['train']['neg_sample_num'])
        test_dataloader=dataloader.DataLoader(test_dataset,batch_size=256,collate_fn=eval_sampler.sample_from_item_pairs,shuffle=True,num_workers=8)  #TODO
        cold_start_dataset=MMCLRData(root_dir=self.train_file_seq,eval='cold_start',neg_sample_num=configs['train']['neg_sample_num'])
        cold_start_dataloader=dataloader.DataLoader(cold_start_dataset,batch_size=256,collate_fn=eval_sampler.sample_from_item_pairs,shuffle=True,num_workers=8)

        configs['data']['user_num'], configs['data']['item_num'] = self.train_mat.shape
        test_data = AllRankTestData(self.test_mat, self.train_mat)
        # self.torch_adj = self._make_torch_adj(self.train_mat)  # TODO
        self.test_dataloader = dataloader.DataLoader(test_data, batch_size=configs['test']['batch_size'], shuffle=False, num_workers=0)




