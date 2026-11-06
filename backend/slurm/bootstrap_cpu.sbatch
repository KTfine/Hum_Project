#!/usr/bin/env bash
#SBATCH --job-name=minicpmo45-bootstrap
#SBATCH --partition=i64m512u
#SBATCH --time=12:00:00
#SBATCH --cpus-per-task=8
#SBATCH --mem=32G
#SBATCH --output=/hpc2hdd/home/yliu674/aiaa3800/MiniCPM-o-4.5-service/logs/slurm/%x_%j.out
#SBATCH --error=/hpc2hdd/home/yliu674/aiaa3800/MiniCPM-o-4.5-service/logs/slurm/%x_%j.err

set -euo pipefail
cd /hpc2hdd/home/yliu674/aiaa3800/MiniCPM-o-4.5-service
exec bash scripts/bootstrap_cpu.sh
