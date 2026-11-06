#!/usr/bin/env bash
#SBATCH --job-name=minicpmo45-serve
#SBATCH --partition=emergency_gpu
#SBATCH --qos=emergency_gpu
#SBATCH --time=00:30:00
#SBATCH --signal=B:TERM@60
#SBATCH --gres=gpu:a800:1
#SBATCH --cpus-per-task=8
#SBATCH --mem=64G
#SBATCH --output=/hpc2hdd/home/yliu674/aiaa3800/MiniCPM-o-4.5-service/logs/slurm/%x_%j.out
#SBATCH --error=/hpc2hdd/home/yliu674/aiaa3800/MiniCPM-o-4.5-service/logs/slurm/%x_%j.err

set -euo pipefail
export OMP_NUM_THREADS="${SLURM_CPUS_PER_TASK:-8}"
cd /hpc2hdd/home/yliu674/aiaa3800/MiniCPM-o-4.5-service
exec bash scripts/launch_service.sh
