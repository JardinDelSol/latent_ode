###########################
# Latent ODEs for Irregularly-Sampled Time Series
# Author: Yulia Rubanova
###########################

import numpy as np
import torch
import torch.nn as nn
from torch.nn.functional import relu

import lib.utils as utils
from lib.encoder_decoder import *
from lib.likelihood_eval import *

from torch.distributions.multivariate_normal import MultivariateNormal
from torch.distributions.normal import Normal
from torch.nn.modules.rnn import GRUCell, LSTMCell, RNNCellBase

from torch.distributions.normal import Normal
from torch.distributions import Independent
from torch.nn.parameter import Parameter
from lib.base_models import Baseline


class ODE_RNN(Baseline):
    def __init__(
        self,
        input_dim,
        latent_dim,
        device=torch.device("cpu"),
        z0_diffeq_solver=None,
        n_gru_units=100,
        n_units=100,
        concat_mask=False,
        obsrv_std=0.1,
        use_binary_classif=False,
        classif_per_tp=False,
        n_labels=1,
        train_classif_w_reconstr=False,
    ):

        Baseline.__init__(
            self,
            input_dim,
            latent_dim,
            device=device,
            obsrv_std=obsrv_std,
            use_binary_classif=use_binary_classif,
            classif_per_tp=classif_per_tp,
            n_labels=n_labels,
            train_classif_w_reconstr=train_classif_w_reconstr,
        )

        ode_rnn_encoder_dim = latent_dim

        self.ode_gru = Encoder_z0_ODE_RNN(
            latent_dim=ode_rnn_encoder_dim,
            input_dim=(input_dim) * 2,  # input and the mask
            z0_diffeq_solver=z0_diffeq_solver,
            n_gru_units=n_gru_units,
            device=device,
        ).to(device)

        self.z0_diffeq_solver = z0_diffeq_solver

        self.decoder = nn.Sequential(
            nn.Linear(latent_dim, n_units), nn.Tanh(), nn.Linear(n_units, input_dim),
        )

        utils.init_network_weights(self.decoder)

    def get_reconstruction(
        self,
        time_steps_to_predict,
        data,
        truth_time_steps,
        mask=None,
        n_traj_samples=None,
        mode=None,
        test=False,
    ):

        # if (len(truth_time_steps) != len(time_steps_to_predict)) or (torch.sum(time_steps_to_predict - truth_time_steps) != 0):
        # 	raise Exception("Extrapolation mode not implemented for ODE-RNN")

        # # time_steps_to_predict and truth_time_steps should be the same
        # assert(len(truth_time_steps) == len(time_steps_to_predict))
        # assert(mask is not None)

        data_and_mask = data
        if mask is not None:
            data_and_mask = torch.cat([data, mask], -1)
        # print("Get reconstruction")
        # print("time_step_to_predict shape: ", time_steps_to_predict.shape)
        # print("data shape: ", data.shape)
        # print("observed tp shape: ", truth_time_steps.shape)
        # print("mask shape: ", mask.shape)
        # print("data with mask shape: ", data_and_mask.shape)

        y_i, y_std, latent_ys, _, last_ti = self.ode_gru.run_odernn(
            data_and_mask, truth_time_steps, run_backwards=False
        )

        if test:
            y_i, yi_std, latent_ys_pred = self.ode_gru.extrap_odernn(
                data_and_mask,
                time_steps_to_predict,
                y_i,
                y_std,
                last_ti,
                self.decoder,
                run_backwards=False,
            )

            latent_ys_pred = latent_ys_pred.permute(0,2,1,3)
            last_hidden_pred = latent_ys[:,:,-1,:]
            # print('latent_ys_pred shape:', latent_ys_pred.shape)
        

        latent_ys = latent_ys.permute(0, 2, 1, 3)
        last_hidden = latent_ys[:, :, -1, :]

        # print('latent_ys shape:', latent_ys.shape)
        

        # assert(torch.sum(int_lambda[0,0,-1,:] <= 0) == 0.)

        outputs = self.decoder(latent_ys)
        # Shift outputs for computing the loss -- we should compare the first output to the second data point, etc.
        first_point = data[:, 0, :]
        outputs = utils.shift_outputs(outputs, first_point)

        extra_info = {
            "first_point": (latent_ys[:, :, -1, :], 0.0, latent_ys[:, :, -1, :])
        }

        if self.use_binary_classif:
            if self.classif_per_tp:
                extra_info["label_predictions"] = self.classifier(latent_ys)
            else:
                extra_info["label_predictions"] = self.classifier(last_hidden).squeeze(
                    -1
                )

        # outputs shape: [n_traj_samples, n_traj, n_tp, n_dims]
        return outputs, extra_info

