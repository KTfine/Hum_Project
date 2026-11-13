#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
# shellcheck disable=SC1091
source "${SCRIPT_DIR}/common.sh"

printf 'Current snapshot only; Slurm makes the final scheduling decision.\n\n'
sinfo -p emergency_gpu,emergency_gpua40 -N -o '%P|%N|%T|%G|%C|%m'
printf '\nQueued jobs:\n'
squeue -p emergency_gpu,emergency_gpua40 -o '%i|%P|%T|%M|%l|%D|%R'
printf '\nDefault service submission is eligible for both partitions.\n'
printf 'Default A800: sbatch slurm/serve.sbatch\n'
printf 'Force A40:   sbatch -p emergency_gpua40 --qos=emergency_gpua40 --gres=gpu:a40:1 slurm/serve.sbatch\n'
