# implemented by JunfengHu
# created time: 7/20/2019

import torch
from torch.utils.data import DataLoader
import numpy as np
from utils import Progbar
from choose_dataset import DatasetChooser
from loss import loss as Loss
import utils
import torch.optim as optim
import config
from plot_animation import plot_animation
import os
from ST_HMR import ST_HMR
from HMR import HMR
from ERD import ERD
from GRU import GRU
from LSTM3lr import LSTM3lr

def choose_net(config):

    if config.model is 'ST_HMR':
        net = ST_HMR(config)
    elif config.model is 'HMR':
        net = HMR(config)
    elif config.model is 'ERD':
        net = ERD(config)
    elif config.model is 'GRU':
        net = GRU(config)
    elif config.model is 'LSTM3lr':
        net = LSTM3lr(config)
    return net

def train(config):

    print('Start Training the Model!')

    # generate data loader
    choose = DatasetChooser(config)
    train_dataset, bone_length = choose(train=True)
    train_loader = DataLoader(train_dataset, batch_size=config.batch_size, shuffle=True)
    test_dataset, _ = choose(train=False)
    test_loader = DataLoader(test_dataset, batch_size=config.batch_size, shuffle=True)
    prediction_dataset, bone_length = choose(prediction=True)
    x_test, y_test, dec_in_test = prediction_dataset
    print()

    device = torch.device("cuda:0" if torch.cuda.is_available() else "cpu")
    print('Device {} will be used to save parameters'.format(device))
    torch.cuda.manual_seed(112858)
    net = choose_net(config)
    net.to(device)
    print('Total param number:' + str(sum(p.numel() for p in net.parameters())))
    print('Encoder param number:' + str(sum(p.numel() for p in net.encoder_cell.parameters())))
    print('Decoder param number:' + str(sum(p.numel() for p in net.decoder.parameters())))
    if torch.cuda.device_count() > 1:
        print("Let's use {} GPUs!".format(str(torch.cuda.device_count())))
    net = torch.nn.DataParallel(net)#, device_ids=[1, 2, 3]) # device_ids=[1, 2, 3]
    #net.load_state_dict(torch.load('./model/Epoch_84 Error0.8422.pth', map_location='cuda:0'))

    optimizer = optim.Adam(net.parameters(), lr=config.learning_rate)

    # Save model
    checkpoint_dir = './model/'
    if not (os.path.exists(checkpoint_dir)):
        os.makedirs(checkpoint_dir)

    best_error = float('inf')
    best_error_list = None
    for epoch in range(config.max_epoch):
        print("At epoch:{}".format(str(epoch + 1)))
        prog = Progbar(target=config.training_size)
        prog_valid = Progbar(target=config.validation_size)

        # Train
        #with torch.autograd.set_detect_anomaly(True):
        for it in range(config.training_size):
            # for k in range(1):
            #     ind = 0
            #     for i, data in enumerate(train_loader, 0):
            #         if ind == 0:
            #             encoder_inputs = data['encoder_inputs'].float().to(device)
            #             decoder_inputs = data['decoder_inputs'].float().to(device)
            #             decoder_outputs = data['decoder_outputs'].float().to(device)
            #             ind = 1
            #         else:
            #             encoder_inputs = torch.cat([data['encoder_inputs'].float().to(device), encoder_inputs], dim=0)
            #             decoder_inputs = torch.cat([data['decoder_inputs'].float().to(device), decoder_inputs], dim=0)
            #             decoder_outputs = torch.cat([data['decoder_outputs'].float().to(device), decoder_outputs], dim=0)
            for i, data in enumerate(train_loader, 0):
                encoder_inputs = data['encoder_inputs'].float().to(device)
                decoder_inputs = data['decoder_inputs'].float().to(device)
                decoder_outputs = data['decoder_outputs'].float().to(device)
                prediction = net(encoder_inputs, decoder_inputs, train=True)

                loss = Loss(prediction, decoder_outputs, bone_length, config)
                net.zero_grad()
                loss.backward()
                _ = torch.nn.utils.clip_grad_norm_(net.parameters(), 5)
                optimizer.step()
            prog.update(it + 1, [("Training Loss", loss.item())])

        # Test
        with torch.no_grad():
            for it in range(config.validation_size):
                for j in range(1):
                    for i, data in enumerate(test_loader, 0):
                        if j == 0 and i == 0:
                            encoder_inputs = data['encoder_inputs'].float().to(device)
                            decoder_inputs = data['decoder_inputs'].float().to(device)
                            decoder_outputs = data['decoder_outputs'].float().to(device)
                        else:
                            encoder_inputs = torch.cat([data['encoder_inputs'].float().to(device), encoder_inputs], dim=0)
                            decoder_inputs = torch.cat([data['decoder_inputs'].float().to(device), decoder_inputs], dim=0)
                            decoder_outputs = torch.cat([data['decoder_outputs'].float().to(device), decoder_outputs], dim=0)
                prediction = net(encoder_inputs, decoder_inputs, train=False)
                loss = Loss(prediction, decoder_outputs, bone_length, config)
                prog_valid.update(it+1, [("Testing Loss", loss.item())])

        # Test prediction
        actions = list(x_test.keys())
        y_predict = {}
        with torch.no_grad():
            for act in actions:
                x_test_ = torch.from_numpy(x_test[act]).float().to(device)
                dec_in_test_ = torch.from_numpy(dec_in_test[act]).float().to(device)
                pred = net(x_test_, dec_in_test_, train=False)
                pred = pred.cpu().numpy()
                y_predict[act] = pred

        error_actions = 0.0
        for act in actions:
            if config.datatype == 'lie':
                mean_error, _ = utils.mean_euler_error(config, act, y_predict[act], y_test[act][:, :10, :])
                error = mean_error[[1, 3, 7, 9]]
            error_actions += error.mean()
        error_actions /= len(actions)
        if error_actions < best_error:
            best_error_list = error
            best_error = error_actions
            torch.save(net.state_dict(),'./model/ERDEpoch_' + str(epoch + 1) + ' Error' + str(round(best_error, 4)) + '.pth')
        print('Current best:' + str(round(best_error_list[0], 2))+ ' ' + str(round(best_error_list[1], 2)) +
                                    ' ' + str(round(best_error_list[2], 2)) + ' ' + str(round(best_error_list[3], 2)))


def prediction(config, checkpoint_filename):

    # Start testing model!

    # generate data loader
    config.output_window_size = 75
    choose = DatasetChooser(config)
    if config.dataset is 'Human':
        _, _ = choose(train=True) # get mean value etc for unnorm

    prediction_dataset, bone_length = choose(prediction=True)
    x_test, y_test, dec_in_test = prediction_dataset

    actions = list(x_test.keys())
    device = torch.device("cuda:0" if torch.cuda.is_available() else "cpu")
    print('Device {} will be used to save parameters'.format(device))
    torch.cuda.manual_seed(973)
    net = choose_net(config)
    net.to(device)
    print('Total param number:' + str(sum(p.numel() for p in net.parameters())))
    print('Encoder param number:' + str(sum(p.numel() for p in net.encoder_cell.parameters())))
    print('Decoder param number:' + str(sum(p.numel() for p in net.decoder.parameters())))

    #if torch.cuda.device_count() > 1:
    #    print("Let's use {} GPUs!".format(str(torch.cuda.device_count())))
    net = torch.nn.DataParallel(net)
    net.load_state_dict(torch.load(checkpoint_filename, map_location='cuda:0'))
    y_predict = {}
    with torch.no_grad():
        # This loop runs only once.
        for act in actions:
            x_test_ = torch.from_numpy(x_test[act]).float().to(device)
            dec_in_test_ = torch.from_numpy(dec_in_test[act]).float().to(device)
            pred = net(x_test_, dec_in_test_, train=True)
            pred = pred.cpu().numpy()
            y_predict[act] = pred

    for act in actions:
        if config.datatype == 'lie':
            mean_error, _ = utils.mean_euler_error(config, act, y_predict[act], y_test[act])

            for i in range(y_predict[act].shape[0]):
                if config.dataset == 'Human':
                    y_p = utils.unNormalizeData(y_predict[act][i], config.data_mean, config.data_std, config.dim_to_ignore)
                    y_t = utils.unNormalizeData(y_test[act][i], config.data_mean, config.data_std, config.dim_to_ignore)
                    expmap_all = utils.revert_coordinate_space(np.vstack((y_t, y_p)), np.eye(3), np.zeros(3))
                    y_p = expmap_all[config.output_window_size:]
                    y_t = expmap_all[:config.output_window_size]
                else:
                    y_p = y_predict[act][i]
                    y_t = y_test[act][i]

                y_p_xyz = utils.fk(y_p, config, bone_length)
                y_t_xyz = utils.fk(y_t, config, bone_length)

                filename = act + '_' + str(i)
                if config.visualize:
                    # 蓝色是我的
                    pre_plot = plot_animation(y_t_xyz, y_p_xyz, config, filename)
                    pre_plot.plot()

if __name__ == '__main__':

    config = config.TrainConfig('Human', 'lie', 'all')
    #prediction(config, './model/Epoch_1 Error0.9288.pth')
    train(config)