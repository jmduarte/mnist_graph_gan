import setGPU

# from profile import profile
# from time import sleep

import torch
from model import Graph_Generator, Graph_Discriminator
from superpixels_dataset import SuperpixelsDataset
from torch.utils.data import DataLoader
from torch.distributions.normal import Normal
from torch.autograd import Variable
from torch.autograd import grad as torch_grad

from skimage.draw import draw

import torch.optim as optim
from tqdm import tqdm

import matplotlib.pyplot as plt
plt.switch_backend('agg')
import matplotlib.cm as cm

import numpy as np

import os
from os import listdir
from os.path import join, isdir
import sys
import tarfile
import urllib

torch.cuda.set_device(0)

url = 'http://ls7-www.cs.uni-dortmund.de/cvpr_geometric_dl/mnist_superpixels.tar.gz'

#Have to specify 'name' and 'start_epoch' if True
LOAD_MODEL = False

WGAN = False
LSGAN = True #WGAN must be false otherwise it'll just be WGAN
TRAIN = True
NUM = -1 #-1 means all numbers
INT_DIFFS = True
GRU = False

node_feat_size = 3 # 2 coords + I
#edge network params
fe_hidden_size = 256
fe_out_size = 128
#message passing network params (either GRU or vanilla network)
mp_hidden_size = 256
mp_num_layers = 2
dropout = 0.3
leaky_relu_alpha = 0.2
num_hits = 75
#learning rates
lr_disc = 0.00001
lr_gen = 0.00001
#number of critic/discriminator iterations for every generator iteration
num_critic = 1
#number of rnn iterations
num_iters = 1
#latent vector size of each node (incl node feature size)
hidden_node_size = 64
#wgan gradient penalty weight
gp_weight = 10
beta1 = 0.5

#max size possible for caltech imperium GPUs
if(WGAN):
    batch_size = 16
else:
    batch_size = 32

num_epochs = 2000

torch.manual_seed(4)
torch.autograd.set_detect_anomaly(True)

name = "58_lsgan_no_gru_all_nums"

dirs = listdir('.')
if('models' not in dirs):
    os.mkdir('./models')
if('losses' not in dirs):
    os.mkdir('./losses')
if('args' not in dirs):
    os.mkdir('./args')
if('figs' not in dirs):
    os.mkdir('./figs')
if('dataset' not in dirs):
    os.mkdir('./dataset')

    file_tmp = urllib.urlretrieve(url, filename=None)[0]
    tar = tarfile.open(file_tmp)
    tar.extractall('./dataset/')

del dirs

onlydirs = [f for f in listdir('models/') if isdir(join('models/', f))]
if (name in onlydirs):
    print("name already used")
    if(not LOAD_MODEL):
        sys.exit()
else:
    os.mkdir('./losses/' + name)
    os.mkdir('./models/' + name)
    os.mkdir('./figs/' + name)

del onlydirs

f = open("args/" + name + ".txt", "w+")
f.write(str(locals()))
f.close()

print(name)

#Change to True !!
X = SuperpixelsDataset(num_hits, train=TRAIN, num=NUM)

# print("loading")

X_loaded = DataLoader(X, shuffle=True, batch_size=batch_size)

# print("loaded")

if(LOAD_MODEL):
    start_epoch = 1000
    G = torch.load("models/" + name + "/G_" + str(start_epoch) + ".pt")
    D = torch.load("models/" + name + "/D_" + str(start_epoch) + ".pt")
else:
    start_epoch = 0
    G = Graph_Generator(node_feat_size, fe_hidden_size, fe_out_size, mp_hidden_size, mp_num_layers, num_iters, num_hits, dropout, leaky_relu_alpha, hidden_node_size=hidden_node_size, int_diffs=INT_DIFFS, gru=GRU).cuda()
    D = Graph_Discriminator(node_feat_size, fe_hidden_size, fe_out_size, mp_hidden_size, mp_num_layers, num_iters, num_hits, dropout, leaky_relu_alpha, hidden_node_size=hidden_node_size, int_diffs=INT_DIFFS, gru=GRU).cuda()

if(WGAN):
    G_optimizer = optim.RMSprop(G.parameters(), lr = lr_gen)
    D_optimizer = optim.RMSprop(D.parameters(), lr = lr_disc)
else:
    G_optimizer = optim.Adam(G.parameters(), lr = lr_gen, betas=(beta1, 0.999))
    D_optimizer = optim.Adam(D.parameters(), lr = lr_disc, betas=(beta1, 0.999))

normal_dist = Normal(0, 0.2)

def wasserstein_loss(y_out, y_true):
    return -torch.mean(y_out * y_true)

if(WGAN):
    criterion = wasserstein_loss
else:
    if(LSGAN):
        criterion = torch.nn.MSELoss()
    else:
        criterion = torch.nn.BCELoss()

# print(criterion(torch.tensor([1.0]),torch.tensor([-1.0])))

def gen(num_samples, noise=0):
    if(noise == 0):
        noise = normal_dist.sample((num_samples, num_hits, hidden_node_size)).cuda()

    x = noise
    del noise

    x = G(x)
    return x

def draw_graph(graph, node_r, im_px):
    imd = im_px + node_r
    img = np.zeros((imd, imd), dtype=np.float)

    circles = []
    for node in graph:
        circles.append((draw.circle_perimeter(int(node[1]), int(node[0]), node_r), draw.circle(int(node[1]), int(node[0]), node_r), node[2]))

    for circle in circles:
        img[circle[1]] = circle[2]

    return img

def save_sample_outputs(name, epoch, dlosses, glosses):
    fig = plt.figure(figsize=(10,10))

    num_ims = 100
    node_r = 30
    im_px = 1000

    gen_out = gen(batch_size).cpu().detach().numpy()

    for i in range(int(num_ims/batch_size)):
        gen_out = np.concatenate((gen_out, gen(batch_size).cpu().detach().numpy()), 0)

    gen_out = gen_out[:num_ims]

    gen_out[gen_out > 0.47] = 0.47
    gen_out[gen_out < -0.5] = -0.5

    gen_out = gen_out*[im_px, im_px, 1] + [(im_px+node_r)/2, (im_px+node_r)/2, 0.55]

    for i in range(1, num_ims+1):
        fig.add_subplot(10, 10, i)
        im_disp = draw_graph(gen_out[i-1], node_r, im_px)
        plt.imshow(im_disp, cmap=cm.gray_r, interpolation='nearest')
        plt.axis('off')

    print("Epoch: " + str(epoch))

    plt.savefig("figs/" +name + "/" + str(epoch) + ".png")
    plt.close()

    fig = plt.figure()
    ax1 = fig.add_subplot(1, 2, 1)
    ax1.plot(dlosses)
    ax1.set_title('Discriminator')
    ax2 = fig.add_subplot(1, 2, 2)
    ax2.plot(glosses)
    ax2.set_title('Generator')

    plt.savefig("losses/"+ name +"/"+ str(epoch) + ".png")
    plt.close()

def save_models(name, epoch):
    torch.save(G, "models/" + name + "/G_" + str(epoch) + ".pt")
    torch.save(D, "models/" + name + "/D_" + str(epoch) + ".pt")

#from https://github.com/EmilienDupont/wgan-gp
def gradient_penalty(real_data, generated_data):
        batch_size = real_data.size()[0]

        # Calculate interpolation
        alpha = torch.rand(batch_size, 1, 1)
        alpha = alpha.expand_as(real_data).cuda()
        interpolated = alpha * real_data.data + (1 - alpha) * generated_data.data
        interpolated = Variable(interpolated, requires_grad=True).cuda()

        del alpha
        torch.cuda.empty_cache()

        # Calculate probability of interpolated examples
        prob_interpolated = D(interpolated)

        # Calculate gradients of probabilities with respect to examples
        gradients = torch_grad(outputs=prob_interpolated, inputs=interpolated, grad_outputs=torch.ones(prob_interpolated.size()).cuda(), create_graph=True, retain_graph=True, allow_unused=True)[0].cuda()

        gradients = gradients.contiguous()

        # Gradients have shape (batch_size, num_channels, img_width, img_height),
        # so flatten to easily take norm per example in batch
        gradients = gradients.view(batch_size, -1)

        # Derivatives of the gradient close to 0 can cause problems because of
        # the square root, so manually calculate norm and add epsilon
        gradients_norm = torch.sqrt(torch.sum(gradients ** 2, dim=1) + 1e-12)

        # Return gradient penalty
        return gp_weight * ((gradients_norm - 1) ** 2).mean()

def train_D(x):
    D.train()
    D_optimizer.zero_grad()

    run_batch_size = x.shape[0]

    if(not WGAN):
        Y_real = torch.ones(run_batch_size, 1).cuda()
        Y_fake = torch.zeros(run_batch_size, 1).cuda()

    D_real_output = D(x)
    gen_ims = gen(run_batch_size)
    D_fake_output = D(gen_ims)

    if(WGAN):
        D_loss = D_fake_output.mean() - D_real_output.mean() + gradient_penalty(x, gen_ims)
    else:
        D_real_loss = criterion(D_real_output, Y_real)
        D_fake_loss = criterion(D_fake_output, Y_fake)

        D_loss = (D_real_loss + D_fake_loss)/2

    D_loss.backward()
    D_optimizer.step()

    if(WGAN):
        return (D_fake_output.mean() - D_real_output.mean())/2
    else:
        return D_loss.item()

def train_G():
    G.train()
    G_optimizer.zero_grad()

    if(not WGAN):
        Y_real = torch.ones(batch_size, 1).cuda()

    gen_ims = gen(batch_size)

    D_fake_output = D(gen_ims)

    if(WGAN):
        G_loss = -D_fake_output.mean()
    else:
        G_loss = criterion(D_fake_output, Y_real)

    G_loss.backward()
    G_optimizer.step()

    return G_loss.item()

D_losses = []
G_losses = []

# save_models(name, 0)

save_sample_outputs(name, 0, D_losses, G_losses)

# @profile
def train():
    for i in range(start_epoch, num_epochs):
        print("Epoch %d %s" % ((i+1), name))
        D_loss = 0
        G_loss = 0
        for batch_ndx, x in tqdm(enumerate(X_loaded), total=len(X_loaded)):
            if(batch_ndx > 0 and batch_ndx % (num_critic+1) == 0):
                G_loss += train_G()
            else:
                D_loss += train_D(x.cuda())

        D_losses.append(D_loss/len(X_loaded)/2)
        G_losses.append(G_loss/len(X_loaded))

        if((i+1)%5==0):
            save_models(name, i+1)
            save_sample_outputs(name, i+1, D_losses, G_losses)

train()
