#!/usr/bin/env bash
#SBATCH --job-name=minicpmo45-probe
#SBATCH --partition=emergency_gpu
#SBATCH --qos=emergency_gpu
#SBATCH --time=00:10:00
#SBATCH --gres=gpu:a800:1
#SBATCH --cpus-per-task=4
#SBATCH --mem=16G
#SBATCH --output=/hpc2hdd/home/yliu674/aiaa3800/MiniCPM-o-4.5-service/logs/slurm/%x_%j.out
#SBATCH --error=/hpc2hdd/home/yliu674/aiaa3800/MiniCPM-o-4.5-service/logs/slurm/%x_%j.err

set -euo pipefail
cd /hpc2hdd/home/yliu674/aiaa3800/MiniCPM-o-4.5-service
exec bash scripts/probe_gpu.sh
