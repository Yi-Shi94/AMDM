#!/usr/bin/env bash
# Chain 12 h SLURM jobs on one controller run; each job resumes from output/interactive/<RUN>/recovery.pth.
#   RUN=path TASK=path ARGS="--lying_weight 2 --num_envs 512 --minibatch 1024" \
#     sbatch --array=0-3%1 --account=<account> scripts/train_slurm.sbatch
#SBATCH --job-name=amdm-interactive
#SBATCH --gpus=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=16G
#SBATCH --time=12:00:00
set -euo pipefail
: "${TASK:?set TASK=target|path|joystick}"
cd "${SLURM_SUBMIT_DIR}"
export WANDB_MODE="${WANDB_MODE:-offline}" PYTHONUNBUFFERED=1 OMP_NUM_THREADS=4
srun python -m amdm_interactive.train --task "${TASK}" --run "${RUN:-${TASK}}" \
    --checkpoint "${CHECKPOINT:-output/base/amdm_lafan1_t16/model_param.pth}" \
    --updates "${UPDATES:-4000}" ${ARGS:-}
