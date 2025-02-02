###########################
# Latent ODEs for Irregularly-Sampled Time Series
# Author: Yulia Rubanova
###########################

import os
import numpy as np

import torch
import torch.nn as nn

import lib.utils as utils
from lib.diffeq_solver import DiffeqSolver
from generate_timeseries import Periodic_1d
from torch.distributions import uniform

from torch.utils.data import DataLoader
from mujoco_physics import HopperPhysics
from physionet import PhysioNet, variable_time_collate_fn, get_data_min_max
from person_activity import PersonActivity, variable_time_collate_fn_activity

from sklearn import model_selection
import random

#####################################################################################################
def parse_datasets(args, device):
    def basic_collate_fn(
        batch, time_steps, args=args, device=device, data_type="train"
    ):
        batch = torch.stack(batch)
        data_dict = {"data": batch, "time_steps": time_steps}

        data_dict = utils.split_and_subsample_batch(
            data_dict, args, data_type=data_type
        )
        return data_dict

    dataset_name = args.dataset

    n_total_tp = (
        args.timepoints + args.extrap + args.extraprnn
    )  # timepoints = 100, extrap = 1 if True
    max_t_extrap = (
        args.max_t / args.timepoints * n_total_tp
    )  # max_t = 5 subsample from the points in the interval [0, max_tp]

    ########### 1d datasets ###########

    # Sampling args.timepoints time points in the interval [0, args.max_t]
    # Sample points for both training sequence and explapolation (test)
    distribution = uniform.Uniform(
        torch.Tensor([0.0]), torch.Tensor([max_t_extrap])
    )  # Create uniform distribution from the interval [0, max_t_extrap]
    time_steps_extrap = distribution.sample(torch.Size([n_total_tp - 1]))[
        :, 0
    ]  # sample n_total_tp - 1
    time_steps_extrap = torch.cat(
        (torch.Tensor([0.0]), time_steps_extrap)
    )  # add 0.0 to the tp: now total N = n_total_tp
    time_steps_extrap = torch.sort(time_steps_extrap)[0]

    dataset_obj = None
    ##################################################################
    # Sample a periodic function
    dataset_obj = Periodic_1d(
        init_freq=None, init_amplitude=1.0, final_amplitude=1.0, final_freq=None, z0=1.0
    )

    ##################################################################

    if dataset_obj is None:
        raise Exception("Unknown dataset: {}".format(dataset_name))

    dataset = dataset_obj.sample_traj(
        time_steps_extrap, n_samples=args.n, noise_weight=args.noise_weight
    )  # (tp, value) pair

    # Process small datasets
    dataset = dataset.to(device)
    time_steps_extrap = time_steps_extrap.to(device)

    train_y, test_y = utils.split_train_test(
        dataset, train_fraq=0.8
    )  # Train and test data are divided into 8:2 ratio

    n_samples = len(dataset)
    input_dim = dataset.size(-1)

    batch_size = min(args.batch_size, args.n)
    # print("train batch size:", batch_size)
    # print("test batch size: ", args.n)
    train_dataloader = DataLoader(
        train_y,
        batch_size=batch_size,
        shuffle=False,
        collate_fn=lambda batch: basic_collate_fn(
            batch, time_steps_extrap, data_type="train"
        ),
    )  # The masking and other
    test_dataloader = DataLoader(
        test_y,
        batch_size=args.n,
        shuffle=False,
        collate_fn=lambda batch: basic_collate_fn(
            batch, time_steps_extrap, data_type="test"
        ),
    )

    data_objects = {  # "dataset_obj": dataset_obj,
        "train_dataloader": utils.inf_generator(train_dataloader),
        "test_dataloader": utils.inf_generator(test_dataloader),
        "input_dim": input_dim,
        "n_train_batches": len(train_dataloader),
        "n_test_batches": len(test_dataloader),
    }

    return data_objects

