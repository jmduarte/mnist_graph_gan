import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.nn import Parameter
import math

class Graph_Generator(nn.Module):
    def __init__(self, node_size, fe_hidden_size, fe_out_size, mp_hidden_size, mp_num_layers, iters, num_hits, dropout, alpha, hidden_node_size=64, int_diffs=False, gru=True):
        super(Graph_Generator, self).__init__()
        self.node_size = node_size
        self.fe_hidden_size = fe_hidden_size
        self.fe_out_size = fe_out_size
        self.mp_hidden_size = mp_hidden_size
        self.num_hits = num_hits
        self.alpha = alpha
        self.mp_num_layers = mp_num_layers
        self.iters = iters
        self.hidden_node_size = hidden_node_size
        self.gru = gru

        self.fe_in_size = 2*hidden_node_size+2 if int_diffs else 2*hidden_node_size+1
        self.use_int_diffs = int_diffs

        self.fe1 = nn.Linear(self.fe_in_size, fe_hidden_size)
        self.fe2 = nn.Linear(fe_hidden_size, fe_out_size)

        if(self.gru):
            self.fn1 = GRU(fe_out_size + hidden_node_size, mp_hidden_size, mp_num_layers, dropout)
            self.fn2 = nn.Linear(mp_hidden_size, hidden_node_size)
        else:
            self.fn1 = nn.ModuleList()
            self.fn1.append(nn.Linear(fe_out_size + hidden_node_size, mp_hidden_size))
            for i in range(mp_num_layers-1):
                self.fn1.append(nn.Linear(mp_hidden_size, mp_hidden_size))
            # self.fn1 = nn.Linear(fe_out_size + hidden_node_size, mp_hidden_size)
            self.fn2 = nn.Linear(mp_hidden_size, hidden_node_size)

    def forward(self, x):
        batch_size = x.shape[0]
        hidden = self.initHidden(batch_size)

        for i in range(self.iters):
            A = self.getA(x, batch_size)
            A = F.leaky_relu(self.fe1(A), negative_slope=self.alpha)
            A = F.leaky_relu(self.fe2(A), negative_slope=self.alpha)
            A = torch.sum(A.view(batch_size, self.num_hits, self.num_hits, self.fe_out_size), 2)

            x = torch.cat((A, x), 2)
            del A

            x = x.view(batch_size*self.num_hits, 1, self.fe_out_size + self.hidden_node_size)

            if(self.gru):
                x, hidden = self.fn1(x, hidden)
            else:
                for i in range(self.mp_num_layers):
                    # x = self.fn1[i](x)
                    x = F.leaky_relu(self.fn1[i](x), negative_slope=self.alpha)

            x = torch.tanh(self.fn2(x))
            x = x.view(batch_size, self.num_hits, self.hidden_node_size)

        x = x[:,:,:self.node_size]

        return x

    def getA(self, x, batch_size):
        x1 = x.repeat(1, 1, self.num_hits).view(batch_size, self.num_hits*self.num_hits, self.hidden_node_size)
        x2 = x.repeat(1, self.num_hits, 1)

        dists = torch.norm(x2[:, :, :2]-x1[:, :, :2]+1e-12, dim=2).unsqueeze(2)

        if(self.use_int_diffs):
            # int_diffs = ((x2[:, :, 2]-x1[:, :, 2])**2).unsqueeze(2)
            # A = ((1-int_diffs)*torch.cat((x1, x2, dists, int_diffs), 2)).view(batch_size*self.num_hits*self.num_hits, self.fe_in_size)
            int_diffs = ((x2[:, :, 2]-x1[:, :, 2])).unsqueeze(2)
            A = (torch.cat((x1, x2, dists, int_diffs), 2)).view(batch_size*self.num_hits*self.num_hits, self.fe_in_size)
        else:
            A = torch.cat((x1, x2, dists), 2).view(batch_size*self.num_hits*self.num_hits, self.fe_in_size)
        return A

    def initHidden(self, batch_size):
        return torch.zeros(self.mp_num_layers, batch_size*self.num_hits, self.mp_hidden_size).cuda()

class Graph_Discriminator(nn.Module):
    def __init__(self, node_size, fe_hidden_size, fe_out_size, mp_hidden_size, mp_num_layers, iters, num_hits, dropout, alpha, hidden_node_size=64, wgan=False, int_diffs=False, gru=False):
        super(Graph_Discriminator, self).__init__()
        self.node_size = node_size
        self.hidden_node_size = hidden_node_size
        self.fe_hidden_size = fe_hidden_size
        self.fe_out_size = fe_out_size
        self.num_hits = num_hits
        self.alpha = alpha
        self.dropout = dropout
        self.mp_num_layers = mp_num_layers
        self.mp_hidden_size = mp_hidden_size
        self.iters = iters
        self.wgan = wgan
        self.gru = gru

        self.fe_in_size = 2*hidden_node_size+2 if int_diffs else 2*hidden_node_size+1
        self.use_int_diffs = int_diffs

        self.fe1 = nn.Linear(self.fe_in_size, fe_hidden_size)
        self.fe2 = nn.Linear(fe_hidden_size, fe_out_size)

        if(self.gru):
            self.fn1 = GRU(fe_out_size + hidden_node_size, mp_hidden_size, mp_num_layers, dropout)
            self.fn2 = nn.Linear(mp_hidden_size, hidden_node_size)
        else:
            self.fn1 = nn.ModuleList()
            self.fn1.append(nn.Linear(fe_out_size + hidden_node_size, mp_hidden_size))
            for i in range(mp_num_layers-1):
                self.fn1.append(nn.Linear(mp_hidden_size, mp_hidden_size))
            # self.fn1 = nn.Linear(fe_out_size + hidden_node_size, mp_hidden_size)
            self.fn2 = nn.Linear(mp_hidden_size, hidden_node_size)

    def forward(self, x):
        batch_size = x.shape[0]
        hidden = self.initHidden(batch_size)

        x = F.pad(x, (0,self.hidden_node_size - self.node_size,0,0,0,0))

        for i in range(self.iters):
            A = self.getA(x, batch_size)

            A = F.leaky_relu(self.fe1(A), negative_slope=self.alpha)
            A = F.leaky_relu(self.fe2(A), negative_slope=self.alpha)
            A = torch.sum(A.view(batch_size, self.num_hits, self.num_hits, self.fe_out_size), 2)

            x = torch.cat((A, x), 2)
            del A

            x = x.view(batch_size*self.num_hits, 1, self.fe_out_size + self.hidden_node_size)

            if(self.gru):
                x, hidden = self.fn1(x, hidden)
            else:
                for i in range(self.mp_num_layers):
                    # x = self.fn1[i](x)
                    x = F.leaky_relu(self.fn1[i](x), negative_slope=self.alpha)

            x = torch.tanh(self.fn2(x))
            x = x.view(batch_size, self.num_hits, self.hidden_node_size)

        x = torch.mean(x[:,:,:1], 1)

        if(self.wgan):
            return x

        return torch.sigmoid(x)

    def getA(self, x, batch_size):
        x1 = x.repeat(1, 1, self.num_hits).view(batch_size, self.num_hits*self.num_hits, self.hidden_node_size)
        x2 = x.repeat(1, self.num_hits, 1)

        dists = torch.norm(x2[:, :, :2]-x1[:, :, :2] + 1e-12, dim=2).unsqueeze(2)

        if(self.use_int_diffs):
            # int_diffs = ((x2[:, :, 2]-x1[:, :, 2])**2).unsqueeze(2)
            # A = ((1-int_diffs)*torch.cat((x1, x2, dists, int_diffs), 2)).view(batch_size*self.num_hits*self.num_hits, self.fe_in_size)
            int_diffs = ((x2[:, :, 2]-x1[:, :, 2])).unsqueeze(2)
            A = (torch.cat((x1, x2, dists, int_diffs), 2)).view(batch_size*self.num_hits*self.num_hits, self.fe_in_size)
        else:
            A = torch.cat((x1, x2, dists), 2).view(batch_size*self.num_hits*self.num_hits, self.fe_in_size)

        return A

    def initHidden(self, batch_size):
        return torch.zeros(self.mp_num_layers, batch_size*self.num_hits, self.mp_hidden_size).cuda()

class GRU(nn.Module):
    def __init__(self, input_size, mp_hidden_size, num_layers, dropout):
        super(GRU, self).__init__()
        self.input_size = input_size
        self.mp_hidden_size = mp_hidden_size
        self.num_layers = num_layers
        self.dropout = dropout
        self.layers = nn.ModuleList()

        self.layers.append(GRUCell(input_size, mp_hidden_size))
        for i in range(num_layers - 1):
            self.layers.append(GRUCell(mp_hidden_size, mp_hidden_size))

    def forward(self, x, hidden):
        x = x.squeeze()
        hidden[0] = F.dropout(self.layers[0](x, hidden[0].clone()), p = self.dropout)

        for i in range(1, self.num_layers):
            hidden[i] = F.dropout(self.layers[i](hidden[i-1].clone(), hidden[i].clone()), p = self.dropout)

        return hidden[-1].unsqueeze(1).clone(), hidden

class GRUCell(nn.Module):

    """
    An implementation of GRUCell.

    """

    def __init__(self, input_size, mp_hidden_size, bias=True):
        super(GRUCell, self).__init__()
        self.input_size = input_size
        self.mp_hidden_size = mp_hidden_size
        self.bias = bias
        self.x2h = nn.Linear(input_size, 3 * mp_hidden_size, bias=bias)
        self.h2h = nn.Linear(mp_hidden_size, 3 * mp_hidden_size, bias=bias)
        self.reset_parameters()

    def reset_parameters(self):
        for w in self.parameters():
            w.data.uniform_(-0.1, 0.1)

    def forward(self, x, hidden):

        x = x.view(-1, x.size(1))

        gate_x = self.x2h(x)
        gate_h = self.h2h(hidden)

        i_r, i_i, i_n = gate_x.chunk(3, 1)
        h_r, h_i, h_n = gate_h.chunk(3, 1)

        resetgate = torch.sigmoid(i_r + h_r)
        inputgate = torch.sigmoid(i_i + h_i)
        newgate = torch.tanh(i_n + (resetgate * h_n))

        hy = newgate + inputgate * (hidden - newgate)

        return hy

class Gaussian_Discriminator(nn.Module):
    def __init__(self, node_size, fe_hidden_size, fe_out_size, mp_hidden_size, mp_num_layers, iters, num_hits, dropout, alpha, kernel_size, hidden_node_size=64, wgan=False, int_diffs=False, gru=False):
        super(Gaussian_Discriminator, self).__init__()
        self.node_size = node_size
        self.hidden_node_size = hidden_node_size
        self.fe_hidden_size = fe_hidden_size
        self.fe_out_size = fe_out_size
        self.num_hits = num_hits
        self.alpha = alpha
        self.dropout = dropout
        self.mp_num_layers = mp_num_layers
        self.mp_hidden_size = mp_hidden_size
        self.iters = iters
        self.wgan = wgan
        self.gru = gru
        self.kernel_size = kernel_size

        self.fn = nn.Linear(hidden_node_size, hidden_node_size)
        self.fc = nn.Linear(hidden_node_size, 1)

        self.mu = Parameter(torch.Tensor(kernel_size, 2).cuda())
        self.sigma = Parameter(torch.Tensor(kernel_size, 2).cuda())

        self.kernel_weight = Parameter(torch.Tensor(kernel_size).cuda())

        self.glorot(self.mu)
        self.glorot(self.sigma)
        self.kernel_weight.data.uniform_(0, 1)

    def forward(self, x):
        batch_size = x.shape[0]
        x = F.pad(x, (0,self.hidden_node_size - self.node_size,0,0,0,0))

        for i in range(self.iters):
            x1 = x.repeat(1, 1, self.num_hits).view(batch_size, self.num_hits*self.num_hits, self.hidden_node_size)
            y = x.repeat(1, self.num_hits, 1)

            u = y[:,:,:2]-x1[:,:,:2]
            y = self.fn(y)

            # print("test")
            # print(y.shape)

            y2 = torch.zeros(y.shape).cuda()

            for j in range(self.kernel_size):
                w = self.weights(u, j)
                # print(w)
                # print(w.shape)
                # print(y.shape)


                y2 += w.unsqueeze(-1)*self.kernel_weight[j]*y

            x = torch.sum(y2.view(batch_size, self.num_hits, self.num_hits, self.hidden_node_size), 2)
            x = x.view(batch_size, self.num_hits, self.hidden_node_size)

        y = torch.tanh(self.fc(x))
        y = torch.mean(y, 1)

        if(self.wgan):
            return y

        return torch.sigmoid(y)

    def weights(self, u, j):
        # print(u)
        # print(self.mu[j])
        # print(u-self.mu[j])
        return torch.exp(torch.sum((u-self.mu[j])**2*self.sigma[j], dim=-1))

    def initHidden(self, batch_size):
        return torch.zeros(self.mp_num_layers, batch_size*self.num_hits, self.mp_hidden_size).cuda()

    def glorot(self, tensor):
        if tensor is not None:
            stdv = math.sqrt(6.0 / (tensor.size(-2) + tensor.size(-1)))
            tensor.data.uniform_(-stdv, stdv)

    def zeros(self, tensor):
        if tensor is not None:
            tensor.data.fill_(0)
#
# class GMMConv(nn.Module):
#     def __init__(self,
#                  in_channels,
#                  out_channels,
#                  dim,
#                  kernel_size,
#                  bias=True):
#         super(GMMConv, self).__init__()
#
#         self.in_channels = in_channels
#         self.out_channels = out_channels
#         self.dim = dim
#         self.kernel_size = kernel_size
#
#         self.lin = torch.nn.Linear(in_channels,
#                                    out_channels * kernel_size,
#                                    bias=False)
#
#         self.mu = Parameter(torch.Tensor(kernel_size, dim))
#         self.sigma = Parameter(torch.Tensor(kernel_size, dim))
#
#         if bias:
#             self.bias = Parameter(torch.Tensor(out_channels))
#         else:
#             self.register_parameter('bias', None)
#
#         self.reset_parameters()
#
#     def reset_parameters(self):
#         self.glorot(self.mu)
#         self.glorot(self.sigma)
#         self.zeros(self.bias)
#         self.reset(self.lin)
#
#     def forward(self, x, edge_index, pseudo):
#         x = x.unsqueeze(-1) if x.dim() == 1 else x
#         pseudo = pseudo.unsqueeze(-1) if pseudo.dim() == 1 else pseudo
#
#         out = self.lin(x).view(-1, self.kernel_size, self.out_channels)
#         out = self.propagate(edge_index, x=out, pseudo=pseudo)
#
#         if self.bias is not None:
#             out = out + self.bias
#         return out
#
#     def message(self, x_j, pseudo):
#         (E, D), K = pseudo.size(), self.mu.size(0)
#
#         gaussian = -0.5 * (pseudo.view(E, 1, D) - self.mu.view(1, K, D))**2
#         gaussian = gaussian / (EPS + self.sigma.view(1, K, D)**2)
#         gaussian = torch.exp(gaussian.sum(dim=-1, keepdim=True))  # [E, K, 1]
#
#         return (x_j * gaussian).sum(dim=1)
#
#     def glorot(self, tensor):
#         if tensor is not None:
#             stdv = math.sqrt(6.0 / (tensor.size(-2) + tensor.size(-1)))
#             tensor.data.uniform_(-stdv, stdv)
#
#     def zeros(self, tensor):
#         if tensor is not None:
#             tensor.data.fill_(0)
