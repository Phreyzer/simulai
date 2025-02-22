# (C) Copyright IBM Corp. 2019, 2020, 2021, 2022.

#    Licensed under the Apache License, Version 2.0 (the "License");
#    you may not use this file except in compliance with the License.
#    You may obtain a copy of the License at

#           http://www.apache.org/licenses/LICENSE-2.0

#     Unless required by applicable law or agreed to in writing, software
#     distributed under the License is distributed on an "AS IS" BASIS,
#     WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#     See the License for the specific language governing permissions and
#     limitations under the License.


"""
Example Created by:
Prof. Nicolas Spogis, Ph.D.
Chemical Engineering Department
LinkTree: https://linktr.ee/spogis

Simple Bioreactor with Monod Model
"""

"""    Import Python Libraries    """
from argparse import ArgumentParser
from typing import List
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import random
import torch 
torch.set_default_dtype(torch.float64)

from simulai.optimization import Optimizer, PIRMSELoss, ScipyInterface
from simulai.residuals import SymbolicOperator
from simulai.templates import NetworkTemplate, guarantee_device
from simulai.file import SPFile

"""    Variables    """
# Bioreactor
N = 100
n = 100

t_max = 72.0
n_intervals = 72
delta_t = t_max/n_intervals

"""    Initial_Conditions """ 
X0 = 0.05
P0 = 0.00
S0 = 10.00
V0 = 1.00

state_t = np.array([X0, P0, S0, V0])

# Will we train from scratch or restore a 
# pre-trained model from disk ?
parser = ArgumentParser(description="Reading input parameters")
parser.add_argument("--train", type=str, help="Training new model or restoring from disk", default="yes")
args = parser.parse_args()

train = args.train

train = "yes"

if train == "yes":

    """    Kinetics constants """ 
    mumax = 0.20      # 1/hour  - maximum specific growth rate
    Ks = 1.00         # g/liter - half saturation constant

    # Yxs = mass of new cells formed / mass of substrate consumed
    Yxs = 0.5         # g/g

    # Ypx = mass of product formed / mass of product formed
    Ypx = 0.2         # g/g

    Sf = 10.0         # g/liter - Fed substrate concentration
    Flow_Rate = 0.05  # Feed flowrate - l/h


    """    The expressions we aim at minimizing """ 
    f_X_C = "D(X_C, t) - ((-Flow_Rate*X_C/Vol)     +         (mumax*S_C/(Ks + S_C))*X_C)"
    f_P_C = "D(P_C, t) - ((-Flow_Rate*P_C/Vol)     +     Ypx*(mumax*S_C/(Ks + S_C))*X_C)"
    f_S_C = "D(S_C, t) - ((Flow_Rate*(Sf-S_C)/Vol) - (1/Yxs)*(mumax*S_C/(Ks + S_C))*X_C)"
    f_Vol = "D(Vol, t) - (Flow_Rate)"

    input_labels = ["t"]
    output_labels = ["X_C", "P_C", "S_C", "Vol"]

    n_inputs = len(input_labels)
    n_outputs = len(output_labels)

    n_epochs_ini = 5_000    # Maximum number of iterations for ADAM
    n_epochs_min = 500      # Minimum number of iterations for ADAM
    Epoch_Tau = 3.0         # Number o Epochs Decay
    lr = 1e-3               # Initial learning rate for the ADAM algorithm
    def Epoch_Decay(iteration_number):
        if iteration_number<100:
            n_epochs_iter = n_epochs_ini*(np.exp(-iteration_number/Epoch_Tau))
            n_epochs = int(max(n_epochs_iter, n_epochs_min))
        else:
            n_epochs = n_epochs_min
        print("N Epochs:", n_epochs)
        print("Iteration:", iteration_number)
        return n_epochs

    # Local model, which will be replicated for each sub-domain
    depth = 3
    width = 50
    activations_funct = "tanh"
    def model():
      from simulai.regression import SLFNN, ConvexDenseNetwork
      from simulai.models import ImprovedDenseNetwork

      scale_factors = np.array([1, 1, 1, 1])

      # Configuration for the fully-connected network
      config = {
          "layers_units": depth * [width],               # Hidden layers
          "activations": activations_funct,
          "input_size": 1,
          "output_size": 4,
          "name": "net"}
          
      #Instantiating and training the surrogate model
      densenet = ConvexDenseNetwork(**config)
      encoder_u = SLFNN(input_size=1, output_size=width, activation=activations_funct)
      encoder_v = SLFNN(input_size=1, output_size=width, activation=activations_funct)

      class ScaledImprovedDenseNetwork(ImprovedDenseNetwork):
        
        def __init__(self, network=None, encoder_u=None, encoder_v=None, devices="gpu", scale_factors=None):
            
            super(ScaledImprovedDenseNetwork, self).__init__(network=densenet, encoder_u=encoder_u, encoder_v=encoder_v, devices="gpu")
            self.scale_factors = torch.from_numpy(scale_factors.astype("float32")).to(self.device)
            
        
        def forward(self, input_data=None):
            
            return super().forward(input_data)*self.scale_factors
        
      net = ScaledImprovedDenseNetwork(network=densenet, encoder_u=encoder_u, encoder_v=encoder_v, devices="gpu", scale_factors=scale_factors)

      # It prints a summary of the network features
      net.summary()
          
      return net

    # Multifidelity network, a composite model with multiple sub-domain 
    # networks
    def model_():

        from typing import List

        import torch 
        torch.set_default_dtype(torch.float64)

        from simulai.templates import NetworkTemplate, guarantee_device
        import numpy as np
        from simulai.models import ImprovedDenseNetwork
        from simulai.regression import SLFNN, ConvexDenseNetwork
        
        t_max = 72.0
        n_intervals = 72
        delta_t = t_max/n_intervals
        
        depth = 3
        width = 50
        activations_funct = "tanh"
        # Model used for initialization
        def sub_model():
            from simulai.regression import SLFNN, ConvexDenseNetwork
            from simulai.models import ImprovedDenseNetwork

            scale_factors = np.array([1, 1, 1, 1])

            # Configuration for the fully-connected network
            config = {
                "layers_units": depth * [width],               # Hidden layers
                "activations": activations_funct,
                "input_size": 1,
                "output_size": 4,
                "name": "net"}
                
            #Instantiating and training the surrogate model
            densenet = ConvexDenseNetwork(**config)
            encoder_u = SLFNN(input_size=1, output_size=width, activation=activations_funct)
            encoder_v = SLFNN(input_size=1, output_size=width, activation=activations_funct)

            class ScaledImprovedDenseNetwork(ImprovedDenseNetwork):
              
              def __init__(self, network=None, encoder_u=None, encoder_v=None, devices="gpu", scale_factors=None):
                  
                  super(ScaledImprovedDenseNetwork, self).__init__(network=densenet, encoder_u=encoder_u, encoder_v=encoder_v, devices="gpu")
                  self.scale_factors = torch.from_numpy(scale_factors.astype("float32")).to(self.device)
                  
              
              def forward(self, input_data=None):
                  
                  return super().forward(input_data)*self.scale_factors
              
            net = ScaledImprovedDenseNetwork(network=densenet, encoder_u=encoder_u, encoder_v=encoder_v, devices="gpu", scale_factors=scale_factors)

            # It prints a summary of the network features
            net.summary()
                
            return net

        # Initialization for the multifidelity network
        models_list = [sub_model() for i in range(n_intervals)]

        # Prototype for the multifidelity network
        class MultiNetwork(NetworkTemplate):

            def __init__(self, models_list:List[NetworkTemplate]=None,
                         delta_t:float=None, device:str='cpu') -> None:

                super(MultiNetwork, self).__init__()

                for i, model in enumerate(models_list):
                    self.set_network(net=model, index=i)

                self.delta_t = delta_t
                self.device = device

            def set_network(self, net:NetworkTemplate=None, index:int=None) -> None:

                setattr(self, f"worker_{index}", net)

                self.add_module(f"worker_{index}", net)

            def _eval_interval(self, index:int=None, input_data:torch.Tensor=None) -> torch.Tensor:

                input_data = input_data[:, None]
                return getattr(self, f"worker_{index}").eval(input_data=input_data)

            def eval(self, input_data:np.ndarray=None) -> np.ndarray:
 
                eval_indices_float = input_data/delta_t
                eval_indices = np.where(eval_indices_float > 0,
                                        np.floor(eval_indices_float - 1e-13).astype(int),
                                        eval_indices_float.astype(int))

                eval_indices = eval_indices.flatten().tolist()

                input_data = input_data - self.delta_t*np.array(eval_indices)[:, None]

                return np.vstack([self._eval_interval(index=i, input_data=idata) \
                                                     for i, idata in zip(eval_indices, input_data)])

            def summary(self):

                print(self)

        multi_net = MultiNetwork(models_list=models_list, delta_t=delta_t)

        return multi_net

    net_ = model()
    multi_net = model_()

    optimizer_config = {"lr": lr}
    optimizer = Optimizer("adam", params=optimizer_config)

    time_plot = np.empty((0, 1), dtype=float)
    approximated_data_plot = np.empty((0, 1), dtype=float)
    time_eval_plot = np.empty((0, 1), dtype=float)

    ### Run Multifidelity Model
    for i in range(0, int(n_intervals), 1):
        net = net_

        time_train = np.linspace(0, delta_t, n)[:, None]
        time_eval = np.linspace(0, delta_t, n)[:, None]

        # Simple model of flame growth
        initial_state = np.array([state_t])

        residual = SymbolicOperator(
            expressions= [f_X_C, f_P_C, f_S_C, f_Vol],
            input_vars=["t"],
            output_vars=["X_C", "P_C", "S_C", "Vol"],
            function=net,
            constants={"mumax": mumax,
                       "Ks": Ks,
                       "Yxs": Yxs,
                       "Ypx": Ypx,
                       "Sf": Sf,
                       "Flow_Rate": Flow_Rate,
                       },
            engine="torch",
            device="gpu",
        )

        params = {
            "residual": residual,
            "initial_input": np.array([0])[:, None],
            "initial_state": initial_state,
            "weights_residual": [1, 1, 1, 1],
            "initial_penalty": 5e8,
        }

        # Reduce Epochs for sequential PINNs
        get_n_epochs = Epoch_Decay(i)

        # First Evaluation With ADAM Optimizer
        optimizer.fit(
            op=net,
            input_data=time_train,
            n_epochs=get_n_epochs,
            loss="pirmse",
            params=params,
            device="gpu",
        )

        # Seccond Evaluation With L-BFGS-B
        loss_instance = PIRMSELoss(operator=net)

        optimizer_lbfgs = ScipyInterface(
            fun=net,
            optimizer="L-BFGS-B",
            loss=loss_instance,
            loss_config=params,
            optimizer_config={
                "options": {
                    "maxiter": 50000,
                    "maxfun": 50000,
                    "maxcor": 50,
                    "maxls": 50,
                    "ftol": 1.0 * np.finfo(float).eps,
                    "eps": 1e-6,
                }
            },
        )

        optimizer_lbfgs.fit(input_data=time_train)

        # Evaluation in training dataset
        approximated_data = net.eval(input_data=time_eval)

        # Get Last PINN Value and Update as Initial Condition for the Next PINN
        state_t = approximated_data[-1]

        # Initializing the nest sub-model using the current one
        net_ = model()
        state_dict = net.state_dict()
        net_.load_state_dict(state_dict)

        # Storing the current network in the multifidelity
        # model
        multi_net.set_network(net=net, index=i)

    saver = SPFile(compact=False)
    saver.write(
        save_dir='./',
        name="multi_fidelity_Bioreactor_pinn",
        model=multi_net,
        template=model_,
    )

# Restoring the model from disk and using it for making 
# evaluations
else:
    saver = SPFile(compact=False)
    multi_net = saver.read(model_path='./multi_fidelity_Bioreactor_pinn', device='cpu')

    input_labels = ["t"]
    output_labels = ["X_C", "P_C", "S_C", "Vol"]

    multi_net.summary()

    time_plot = np.linspace(0, t_max, 1000)[:, None]

    approximated_data_plot = multi_net.eval(input_data=time_plot)
    
    df = pd.DataFrame(approximated_data_plot, columns = output_labels)
    # Plot Result
    Charts_Dir= './'

    # Compare PINN and EDO Results
    ODE_Results = pd.read_csv("Bioreactor_ODEs.csv")
    Filter_Scale = 50
    ODE_Results_OnlyFewData = ODE_Results[::Filter_Scale]

    plt.figure(1)
    Chart_File_Name = Charts_Dir + 'Bioreactor_ODE_PINN_Concentration_Comparison.png'
    
    plt.scatter(ODE_Results_OnlyFewData["Time"], ODE_Results_OnlyFewData["Cell Conc."], label='ODE - Cell Conc.')
    plt.scatter(ODE_Results_OnlyFewData["Time"], ODE_Results_OnlyFewData["Product Conc."], label='ODE - Product Conc.')
    plt.scatter(ODE_Results_OnlyFewData["Time"], ODE_Results_OnlyFewData["Substrate Conc."], label='ODE - Substrate Conc.')
    plt.plot(time_plot, df['X_C'], label='PINN - Cell Conc.')
    plt.plot(time_plot, df['P_C'], label='PINN - Product Conc.')
    plt.plot(time_plot, df['S_C'], label='PINN - Substrate Conc.')
    
    plt.legend()
    plt.xlabel('Time [hr]')
    plt.ylabel('Concentration [g/liter]')
    plt.savefig(Chart_File_Name)
    plt.show()
    
    plt.figure(2)
    Chart_File_Name = Charts_Dir + 'Bioreactor_ODE_PINN_Volume_Comparison.png'
    
    plt.scatter(ODE_Results_OnlyFewData["Time"], ODE_Results_OnlyFewData["Volume [liter]"], label='ODE - Volume [liter]')
    plt.plot(time_plot, df['Vol'], label='PINN - Volume [liter]')
    
    plt.legend()
    plt.xlabel('Time [hr]')
    plt.ylabel('Volume [liter]')
    plt.savefig(Chart_File_Name)
    plt.show()