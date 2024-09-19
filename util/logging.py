import csv
import wandb
import glob
import torch
import util.mp_util as mp_util 

class CSVLogger(object):
    def __init__(self, log_path):
        self.csvfile = open(log_path, "w")
        self.writer = None
        
    def init_writer(self, keys):
        if self.writer is None:
            self.writer = csv.DictWriter(
                self.csvfile, fieldnames=list(keys), lineterminator="\n"
            )
            self.writer.writeheader()

    def log_epoch(self, data, step=None):
        self.init_writer(data.keys())
        self.writer.writerow(data)
        self.csvfile.flush()

    def __del__(self):
        self.csvfile.close()

class wandbLogger(object):
    def __init__(self, run_name, proj_name):
        wandb.init(project=proj_name, name=run_name)
        self.run_name = wandb.run.name

    def is_root(self):
        return mp_util.is_root_proc()

    def print_log(self, log_dict):
        """
        Print all of the diagnostics from the current iteration
        """
        
        if (mp_util.enable_mp() and self._need_update):
            self._mp_aggregate()

        key_spacing = 15
        format_str = "| %" + str(key_spacing) + "s | %15s |"

        if (self.is_root()):
            vals = []
            print("-" * (22 + key_spacing))
            for key in log_dict:

                val = log_dict[key]
                vals.append(val)

                #prevent print out the distribution or histogram data in console and text
                if isinstance(val, list) and len(val)>1:
                    continue
                elif isinstance(val, torch.Tensor):
                    try:
                        val = val.item()
                    except:
                        pass
                
                if isinstance(val, float):
                    valstr = "%8.3g"%val
                elif isinstance(val, int):
                    valstr = str(val)
                else: 
                    valstr = val

                print(format_str%(key, valstr))
                    
            print("-" * (22 + key_spacing))
        return

    def log_epoch(self, data, step=None):
        if step is None:
            wandb.log(data)
        else:
            wandb.log(data,step=step)

    def get_name(self):
        return wandb.run.name

    def plot_1d_line(self,data_lst):
        time_x = len(data_lst[0])
        xs = list(range(time_x))
        
        wandb.log({wandb.plot.line_series(
          xs=xs,
          ys=list(data_lst),
          keys=["X","Y", "Z"],
          title="Motion plot",
          xname="N")})

    def log_gif(self,gif_dir):
        gif_lst = glob.glob(gif_dir+'/*.gif')
        print(gif_lst)
        for gf in gif_lst:
            wandb.log(
                {"video": wandb.Video(gf, fps=30, format="gif")})
    
class ConsoleCSVLogger(CSVLogger):
    def __init__(self, console_log_interval=1, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.console_log_interval = console_log_interval

    def log_epoch(self, data):
        super().log_epoch(data)

        if data["iter"] % self.console_log_interval == 0:
            print(
                (
                    "Updates {}, num timesteps {}, "
                    "FPS {}, mean/median reward {:.1f}/{:.1f}, "
                    "min/max reward {:.1f}/{:.1f}, "
                    "policy loss {:.5f}"
                ).format(
                    data["iter"],
                    data["total_num_steps"],
                    data["fps"],
                    data["mean_rew"],
                    data["median_rew"],
                    data["min_rew"],
                    data["max_rew"],
                    data["action_loss"],
                ),
                flush=True,
            )
