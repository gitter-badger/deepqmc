import numpy as np
from itertools import islice
import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d import Axes3D
import time
import torch
import torch.nn as nn
from torch.autograd import Variable,grad
import torch.nn.functional as F
import copy
import datetime
import scipy as sp
cmap=plt.get_cmap("plasma")
import pymc3 as pm

from scipy.stats import norm
from pysgmcmc import *

from pysgmcmc.samplers.sghmc import SGHMC
#from pysgmcmc.samplers.sgld import SGLD

def pysgmcmcsampler(dist,sampler_cls=SGHMC, lr=0.1,startfactor=0.2,num_burn_in_steps=0,num_samples=2000):
	rand1 = (torch.randn(1)*startfactor).requires_grad_(True)
	rand2 = (torch.randn(1)*startfactor).requires_grad_(True)
	sampler = sampler_cls(params=(rand1,rand2),lr=lr, negative_log_likelihood=dist)
	_ = [sample for sample, _ in islice(sampler, num_burn_in_steps)]
	samples = np.asarray([sample for sample, _ in islice(sampler, num_samples)])
	plt.plot(rand1.detach().numpy(),rand2.detach().numpy(),marker='.',ms='1',ls='',color='k')
	return samples


def dynamics(dist,pos,stepsize,steps,T):
	pos = pos.detach().clone()
	pos.requires_grad=True
	vel = torch.randn(pos.shape)*T
	v_te2 = vel - stepsize*torch.autograd.grad(dist(pos),pos,create_graph=True,retain_graph=True,grad_outputs=torch.ones(len(pos)))[0]/2
	p_te  = pos + stepsize*v_te2
	for n in range(1,steps):
		v_te2 = v_te2 - stepsize*torch.autograd.grad(dist(pos),pos,create_graph=True,retain_graph=True,grad_outputs=torch.ones(len(pos)))[0]
		p_te  = p_te + stepsize*v_te2
	v_te  = v_te2 - stepsize*torch.autograd.grad(dist(pos),pos,create_graph=True,retain_graph=True,grad_outputs=torch.ones(len(pos)))[0]/2
	return p_te,vel.detach().numpy()


def HMC(dist,stepsize,dysteps,n_walker,steps,dim,startfactor=0.2,T=0.1,presteps=0):
	samples = torch.zeros(steps,n_walker,dim)
	walker = torch.randn(n_walker,dim)*startfactor
	plt.plot(walker.detach().numpy()[:,0],walker.detach().numpy()[:,1],marker='.',ms='1',ls='',color='k')
	v_walker = np.random.normal(size=(n_walker,dim))*startfactor
	distwalker = dist(walker).detach().numpy()
	for i in range(steps+presteps):
		if i>=presteps:
			samples[i-presteps] = walker
		trial,v_trial = dynamics(dist,walker,stepsize,dysteps,T)
		disttrial = dist(trial).detach().numpy()
		ratio = (np.exp(disttrial-distwalker))*(np.exp(0.5*np.sum(v_trial**2,axis=-1)-0.5*np.sum(v_walker**2,axis=-1)))
		smaller_n = (ratio<np.random.uniform(0,1,n_walker)).astype(float)
		larger_n  = np.abs(smaller_n-1)
		smaller = torch.from_numpy(smaller_n).type(torch.FloatTensor)
		larger  = torch.abs(smaller-1)
		walker = trial*larger[:,None] + walker*smaller[:,None]
		v_walker = v_trial*larger_n[:,None] + v_walker*smaller_n[:,None]

	return samples

def metropolis(distribution,startpoint,stepsize,steps,dim,n_walker,startfactor=0.2,presteps=0,interval=None,T=0.2):
	#initialise list to store walker positions
	samples = torch.zeros(steps,n_walker,len(startpoint))
	#another list for the ratios
	ratios = np.zeros((steps,n_walker))
	#initialise the walker at the startposition
	walker = torch.randn(n_walker,dim)*startfactor
	plt.plot(walker.detach().numpy()[:,0],walker.detach().numpy()[:,1],marker='.',ms='1',ls='',color='k')
	distwalker = distribution(walker)
	#loop over proposal steps
	for i in range(presteps+steps):
		#append position of walker to the sample list in case presteps exceeded
		if i > (presteps-1):
			samples[i-presteps]=walker
		#propose new trial position
		#trial = walker + (torch.rand(6)-0.5)*maxstepsize
		#pro = torch.zeros(2)
		pro = (torch.rand(walker.shape)-0.5)*stepsize
		trial = walker + pro
		#calculate acceptance propability
		disttrial = distribution(trial)
		#check if in interval
		if not interval is None:
			inint = torch.tensor(all(torch.tensor(interval[0]).type(torch.FloatTensor)<trial[0]) \
			and all(torch.tensor(interval[1]).type(torch.FloatTensor)>trial[0])).type(torch.FloatTensor)
			disttrial = disttrial*inint

		ratio = np.exp((disttrial.detach().numpy()-distwalker.detach().numpy())/T)
		ratios[i-presteps] = ratio
		#accept trial position with respective propability
		smaller_n = (ratio<np.random.uniform(0,1,n_walker)).astype(float)
		larger_n  = np.abs(smaller_n-1)
		smaller = torch.from_numpy(smaller_n).type(torch.FloatTensor)
		larger  = torch.abs(smaller-1)
		walker = trial*larger[:,None] + walker*smaller[:,None]

		#if ratio > np.random.uniform(0,1):
	#		walker = trial
	#		distwalker = disttrial
	#return list of samples
	#print("variance of acc-ratios = " + str((np.sqrt(np.mean(ratios**2)-np.mean(ratios)**2)).data))
	return samples


class Net(nn.Module):
		def __init__(self):
			super(Net, self).__init__()
			self.NN=nn.Sequential(
					torch.nn.Linear(1, 64),
					torch.nn.ELU(),
					torch.nn.Linear(64, 64),
					torch.nn.ELU(),
					torch.nn.Linear(64, 1)
					)
			self.Lambda=nn.Parameter(torch.Tensor([-1]))	#eigenvalue


		def forward(self,x):
			if type(x) == tuple:
				d = ((x[0]**2+x[1]**2)**(1/2)).view(-1,1)
			else:
				d = torch.norm(x,dim=1).view(-1,1)              #define forward pass
			r = torch.erf(d/0.1)/d         #get inverse distances
			return self.NN(r)[:,0]

net=Net()

maxmin = 5
f = lambda x: - net(x)**2

x,y = torch.meshgrid([torch.linspace(-maxmin,maxmin,100),torch.linspace(-maxmin,maxmin,100)])
G=torch.cat((x,y)).view(2,100,100).transpose(0,-1)
P=np.zeros((100,100))
for i in range(100):

	P[i] = -f(G[i]).detach().numpy()



plt.figure(figsize=(9,12))
#_________________________________________________________________
plt.subplot2grid((2,2),(0,0))
plt.imshow(P,extent=[-maxmin,maxmin,-maxmin,maxmin],cmap=cmap)
#_________________________________________________________________
n_walker= 30
n_steps = 1000

for i in range(2):
	for j in range(2):
		if not i+j==0:
			plt.subplot2grid((2,2),(i,j))
			start=time.time()
			POS=np.array(HMC(f,0.1,5,n_walker,n_steps,2,T=0.3*(2*i+j)).detach())
			end=time.time()
			print("HMC done")
			print(np.round(end-start,1))
			plt.hist2d(POS[:,:,0].flatten(),POS[:,:,1].flatten(),range=np.array([[-maxmin,maxmin],[-maxmin,maxmin]]),cmap=cmap,bins=100,normed=True)
			plt.title("HMC t="+str(np.round(end-start,1)))

plt.show()
print(P[0])
exit(0)
#_________________________________________________________________
#for i in range(10):
#	plt.plot(POS[:,i,0],POS[:,i,1],ls='',Marker='.',ms=1)
#_________________________________________________________________
plt.hist2d(POS[:,:,0].flatten(),POS[:,:,1].flatten(),range=np.array([[-maxmin,maxmin],[-maxmin,maxmin]]),cmap=cmap,bins=100,normed=True)
plt.title("HMC t="+str(np.round(end-start,1)))
#_________________________________________________________________
plt.subplot2grid((2,2),(1,0))
start=time.time()
POS = np.array(metropolis(f,np.random.normal(size=2),0.3,n_steps,dim=2,n_walker=n_walker,interval=None,T=0.005).detach())
end=time.time()
print("Metropolis done")
print(np.round(end-start,1))
#_________________________________________________________________

plt.hist2d(POS[:,0].flatten(),POS[:,1].flatten(),range=np.array([[-maxmin,maxmin],[-maxmin,maxmin]]),cmap=cmap,bins=100,normed=True)
plt.title("Metropolis t="+str(np.round(end-start,1)))
#_________________________________________________________________
plt.subplot2grid((2,2),(1,1))
start=time.time()
POS=np.array([pysgmcmcsampler(f,lr=0.001,num_samples=1000).reshape(-1,2) for i in range(3)]).reshape(-1,2)
end=time.time()
print("pysgmcmc done")
print(np.round(end-start,1))
#_________________________________________________________________
plt.hist2d(POS[:,0],POS[:,1],cmap=cmap,bins=100,range=np.array([[-maxmin,maxmin],[-maxmin,maxmin]]),normed=True)
plt.title("pysgmcmc t="+str(np.round(end-start,1)))

plt.show()
