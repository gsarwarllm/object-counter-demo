# Setup from scratch

A step-by-step guide for a machine that has nothing installed yet. No knowledge of the app, Python or Docker is needed. Every action is written out: run the commands **one line at a time**, in order. Paste a line into the terminal, press Enter, and wait until the prompt (`$`) comes back before the next line. Text after `#` is a comment, so you can paste it too.

What you end up with: the object counter running on your machine with the two real models, its two databases, and the Grafana dashboards. To then test every feature, follow [`TESTING-GUIDE.md`](TESTING-GUIDE.md).

## Fastest: GitHub Codespaces (nothing to install)

A codespace is a Linux machine in the cloud with VS Code in your browser. The repository's [`.devcontainer/devcontainer.json`](../.devcontainer/devcontainer.json) sets it up with Docker, and runs `make install` when the codespace is created, so Parts 0 to D step 1 below are not needed. It needs only a browser and a GitHub account with access to the repository. Codespaces are billed to the GitHub account that creates them; personal accounts get a monthly free allowance, and a codespace stops by itself after 30 minutes without activity.

1. Open the repository on GitHub, click the green **Code** button → **Codespaces** tab → **Create codespace on main**.
2. Wait until the setup finishes (about 10 minutes the first time). The terminal at the bottom shows `make install` running and ends with the `make doctor` report and `Ready`.
3. In that terminal, start the app (it keeps running):

   ```bash
   make start
   ```

   Or, for the full demo instead: `make demo` starts everything in Docker with Grafana and Prometheus, fills the dashboards with demo data, starts the MLflow UI in the background and prints every page's address (about 5.5 GB of the codespace's 8 GB; the prompt comes back when it's done).

4. Run `make urls` in a second terminal: it prints this codespace's address of every page ([Demo URLs](DEMO-URLS.md)). Or open the **Ports** tab (next to *Terminal*) → port **5000** → the globe icon, and add `/docs/` to the address (the API has no home page, so the address alone answers `404`). TF Serving (8501) opens the same way; Grafana (3000), Prometheus (9090) and the MLflow UI (5001) too, after `make demo`. To share a page, right-click its port → *Port Visibility* → **Public**.
5. A second terminal: click **+** in the terminal panel. Every command in [`TESTING-GUIDE.md`](TESTING-GUIDE.md) works there as written; open its `localhost` links through the **Ports** tab instead.
6. When you're done: **Code** → **Codespaces** → **...** next to the codespace → **Stop codespace** (or **Delete**, which also frees its storage).

To run the app on your own machine instead, follow the rest of this guide.

## Windows PowerShell, Docker only (no WSL terminal, no make)

For running the app on Windows from **PowerShell**, with nothing installed but Docker Desktop and Git. A setup container does what `make install` does, and the app runs in a container too. What it can't do: the `make` targets (tests, drift reports, releases, the CLI). For those, use the Ubuntu terminal of [Part A](#part-a-windows-with-docker-desktop).

1. **Install Docker Desktop:** [Part A](#part-a-windows-with-docker-desktop) steps 1 and 5–7 (step 8, WSL integration, is not needed here). If the installer asks to install or update WSL, accept: Docker Desktop runs its engine there.
2. **Open PowerShell:** Start → type `PowerShell` → Enter (or a PowerShell tab in Windows Terminal). The prompt looks like `PS C:\Users\you>`.
3. **Install Git for Windows:**

   ```powershell
   winget install --id Git.Git -e
   ```

   Then close PowerShell and open it again, so it finds `git`.
4. **Download the code** into your user folder. The repository is private: a browser window asks you to sign in to GitHub the first time.

   ```powershell
   cd ~
   git clone https://github.com/gsarwarllm/object-counter-demo.git
   cd object-counter-demo
   ```

5. **Set up the models** (about 4 minutes the first time, half a minute later). It ends with `Setup done`:

   ```powershell
   docker compose --profile setup run --rm setup
   ```

6. **Start the app** with TF Serving, MongoDB and PostgreSQL (the first time it builds the app image and downloads the others, about 10 minutes). It ends when the four containers are *Healthy*:

   ```powershell
   docker compose --profile app up -d --wait
   ```

7. **Try it.** Use `curl.exe`, not `curl` (in PowerShell, `curl` is a different command). Readiness should answer `"status":"ok"`; the count answers with the objects in the picture and `"version":"1"`:

   ```powershell
   curl.exe http://localhost:5000/health/ready
   curl.exe -F "threshold=0.5" -F "file=@resources/images/cat.jpg" http://localhost:5000/object-count
   ```

   Or open [http://localhost:5000/docs](http://localhost:5000/docs) in the browser. The `curl` steps of [`TESTING-GUIDE.md`](TESTING-GUIDE.md) work the same way with `curl.exe`.
8. **Optional, the dashboards** (Grafana at [http://localhost:3000](http://localhost:3000), Prometheus at [http://localhost:9090](http://localhost:9090)), and the app's log:

   ```powershell
   docker compose --profile app --profile monitoring up -d --wait
   docker compose logs -f app
   ```

   **Ctrl+C** stops following the log; the app keeps running.
9. **Stop everything** (the counts stay saved):

   ```powershell
   docker compose --profile app --profile monitoring down
   ```

10. **Next time:** start Docker Desktop, open PowerShell, then `cd ~\object-counter-demo` and step 6. **After a `git pull`:** steps 5 and 6, with `--build` added to step 6 (`docker compose --profile app up -d --wait --build`) so the app image is rebuilt.

**What you need**

| | Minimum |
|---|---|
| Computer | Windows 10 (22H2) or 11, or Ubuntu 22.04 or newer |
| Memory (RAM) | 8 GB in the computer (the app and its services use about 2.5 GB) |
| Free disk | 15 GB on Windows (Docker Desktop and Ubuntu included), 6 GB on Linux |
| Internet | about 5 GB is downloaded on the first run |
| GitHub | an account that the repository owner has added (the repository is private) |
| Time | about 45 minutes the first time on Windows (installing WSL and Docker Desktop), 20–30 minutes on Linux, most of it waiting for downloads |

**Order**

| Part | Windows | Linux |
|---|---|---|
| [Codespaces](#fastest-github-codespaces-nothing-to-install) | instead of everything below, in the browser | instead of everything below, in the browser |
| [PowerShell, Docker only](#windows-powershell-docker-only-no-wsl-terminal-no-make) | instead of the parts below, to run the app from PowerShell (no tests or `make` targets) | |
| [0. Clean start](#part-0-clean-start-only-if-the-app-ran-on-this-machine-before) | only if the app ran on this machine before | only if the app ran on this machine before |
| [A. Docker Desktop](#part-a-windows-with-docker-desktop) | yes | skip |
| [B. Get the code](#part-b-get-the-code-windows-and-linux) | yes | yes |
| [C. Docker on Linux](#part-c-docker-on-linux-linux-only) | skip (done in Part A) | yes |
| [D. Install and run](#part-d-install-and-run-windows-and-linux) | yes | yes |
| [E. Stop and start again](#part-e-stop-and-start-again) | whenever you stop or start | whenever you stop or start |

**Why some steps can't be one `make` command.** Parts A to C install what `make` itself needs, or need you: installer windows, an administrator, a restart, a browser login, and the code (the `Makefile` is inside it). Everything after that is one command, `make install`.

**Words used below.** *Terminal*: the window where you type commands. On Windows it is an **Ubuntu** tab in Windows Terminal (see [Part A](#part-a-windows-with-docker-desktop), "Which terminal on Windows") or the Ubuntu window (Start → type `Ubuntu` → Enter); on Linux press **Ctrl+Alt+T**. *Paste* in the terminal: right-click (Windows Ubuntu window) or **Ctrl+Shift+V** (Linux). **Ctrl+C** in a terminal stops the program running in it.

## Part 0: clean start (only if the app ran on this machine before)

1. If a terminal is still running `make run-prod` or `make run` (it prints a log line per request), click into it and press **Ctrl+C**.
2. Open a terminal and go into the old folder (if it is somewhere else, use that path):

   ```bash
   cd ~/object-counter-demo
   ```

3. Stop any app process that is still running in the background, and every container of the app:

   ```bash
   pkill -f counter.entrypoints.webapp || true
   make down
   ```

4. Check that nothing is left. This should print only the header line `NAMES STATUS`:

   ```bash
   docker ps --format 'table {{.Names}}\t{{.Status}}'
   ```

5. **Optional, deletes all saved counts and prediction logs:** remove the database volumes too.

   ```bash
   docker compose --profile app --profile monitoring down -v
   ```

6. **Optional, for a completely fresh download:** delete the old folder (the code, models and Python packages in it). Part B step 3 downloads it again.

   ```bash
   cd ~
   rm -rf ~/object-counter-demo
   ```

7. Windows only, to restart Docker Desktop cleanly: right-click the whale icon in the taskbar (bottom right, click `^` if hidden) → **Quit Docker Desktop**. Then click Start, type `PowerShell`, open *Windows PowerShell*, and run:

   ```powershell
   wsl --shutdown
   ```

   Start Docker Desktop again (Start → type `Docker Desktop` → Enter) and wait until its window says *Engine running* (green, bottom left).

Then continue with Part B (Docker is already installed; if you kept the folder, go straight to Part D).

## Part A: Windows with Docker Desktop

On Windows, the commands run in **Ubuntu inside Windows** (WSL, the Windows Subsystem for Linux), not in Docker Desktop: Docker Desktop has no command line of its own for this; it runs the containers in the background and its window shows them. This way every command in these guides works on Windows exactly as on Linux.

1. **Check virtualization.** Press **Ctrl+Shift+Esc** (Task Manager) → *Performance* → *CPU*. Bottom right it should say *Virtualization: Enabled*. If it says *Disabled*, enable it in the computer's BIOS/UEFI (search the web for your computer model + "enable virtualization"), then come back.
2. **Open PowerShell as administrator:** click Start, type `PowerShell`, right-click *Windows PowerShell* → **Run as administrator** → *Yes*.
3. **Install WSL with Ubuntu** in that PowerShell window:

   ```powershell
   wsl --install -d Ubuntu
   ```

   When it finishes, restart the computer (Start → Power → **Restart**).
4. **Create your Ubuntu user.** After the restart an *Ubuntu* window opens by itself (otherwise: Start → type `Ubuntu` → Enter; the first start takes a minute). It asks for a new user name (lower case, no spaces) and a password twice. The password doesn't show while you type; that is normal. Remember it: every `sudo` command asks for it.
5. **Download Docker Desktop:** open [docker.com/products/docker-desktop](https://www.docker.com/products/docker-desktop/) in the browser → *Download for Windows – AMD64* (or *ARM64* on an ARM laptop).
6. **Install it:** run the downloaded `Docker Desktop Installer.exe` → *Yes*. Keep **Use WSL 2 instead of Hyper-V** ticked → *OK*. At the end click **Close and log out** (or **Close and restart**), and log in to Windows again.
7. **Start Docker Desktop:** Start → type `Docker Desktop` → Enter. Accept the service agreement. Signing in is optional: click **Skip** (and *Skip* for the survey). Wait until the bottom left says *Engine running*.
8. **Connect it to Ubuntu:** in Docker Desktop click the gear icon (*Settings*, top right) → *Resources* → *WSL integration* → switch on **Ubuntu** → **Apply & restart**.
9. **Close the Ubuntu window and open a new one** (Start → type `Ubuntu` → Enter), so it picks up Docker.
10. **Check Docker** in the Ubuntu window:

    ```bash
    docker run --rm hello-world
    ```

    It should print *Hello from Docker!*. If it says `docker: command not found` or `Cannot connect to the Docker daemon`, check step 7 (*Engine running*) and step 8, then repeat step 9.
11. **Check Compose:**

    ```bash
    docker compose version
    ```

    It should print `Docker Compose version v2...`.

From now on, **every command goes into Ubuntu**, and Docker Desktop must be running whenever you use the app. Continue with Part B.

**Which terminal on Windows.** Use an Ubuntu terminal, through either of these:

| Way | How to open it | Notes |
|---|---|---|
| **Windows Terminal** (recommended) | Start → type `Terminal` → Enter, then the **˅** arrow next to the tabs → **Ubuntu** | Built into Windows 11; on Windows 10 install *Windows Terminal* from the Microsoft Store. Tabs, easy copy and paste (**Ctrl+Shift+C** / **Ctrl+Shift+V**). To open Ubuntu by default: **˅** → *Settings* → *Default profile* → **Ubuntu** → *Save*. A second terminal is a new tab: **˅** → **Ubuntu** again. |
| The Ubuntu window | Start → type `Ubuntu` → Enter | Paste with a right-click |

A **PowerShell** or **Command Prompt** tab doesn't work for these steps: it has no `make` and doesn't use Linux paths (to only run the app from PowerShell, see [PowerShell, Docker only](#windows-powershell-docker-only-no-wsl-terminal-no-make)). You can tell an Ubuntu tab by its prompt, `yourname@computer:~$`; PowerShell shows `PS C:\...>`. If you opened PowerShell by mistake, type `wsl` and press Enter: that tab becomes Ubuntu.

## Part B: get the code (Windows and Linux)

All commands go into the terminal (on Windows: the Ubuntu window).

**1. Install the basic tools:** git (downloads the code), make (runs the steps), curl (downloads and sends test requests) and gh (logs in to GitHub). It asks for your password; it doesn't show while you type:

```bash
sudo apt update
sudo apt install -y git make curl gh
```

**2. Log in to GitHub** (needed because the repository is private):

```bash
gh auth login
```

Answer its questions with the arrow keys and Enter: *Where do you use GitHub?* → **GitHub.com**; *preferred protocol* → **HTTPS**; *Authenticate Git with your GitHub credentials?* → **Yes**; *How would you like to authenticate?* → **Login with a web browser**. It shows a one-time code like `ABCD-1234`: copy it, press Enter, and enter the code in the browser page that opens (on Windows, if no browser opens, open [github.com/login/device](https://github.com/login/device) yourself), then click *Authorize*. Back in the terminal it says *Logged in as ...*. Then:

```bash
gh auth setup-git
```

**3. Download the code** into your home folder and go into it:

```bash
cd ~
git clone https://github.com/gsarwarllm/object-counter-demo.git
cd ~/object-counter-demo
```

On Windows, keep it in the Ubuntu home folder (`~`), never under `/mnt/c/...`: the Windows drive is much slower from Ubuntu and breaks file permissions. **Every later command runs inside this folder.** Whenever you open a new terminal, first run `cd ~/object-counter-demo`.

Windows: continue with Part D. Linux: continue with Part C.

## Part C: Docker on Linux (Linux only)

1. Install Docker and Compose v2, and allow your user to run Docker without `sudo` (asks for your password):

   ```bash
   make install-docker
   ```

2. Restart, so the docker group applies (logging out and in again also works):

   ```bash
   sudo reboot
   ```

3. After the restart, open a terminal again (**Ctrl+Alt+T**), go into the folder and check Docker. It should print *Hello from Docker!*:

   ```bash
   cd ~/object-counter-demo
   docker run --rm hello-world
   ```

   If it says `permission denied ... docker.sock`, step 2 didn't happen: log out and in again.
4. Check Compose. It should print `Docker Compose version 2...`:

   ```bash
   docker compose version
   ```

## Part D: install and run (Windows and Linux)

**1. Install everything the app needs** with one command: uv (installs the right Python), the app's Python packages, the model registry (MLflow, about 640 MB), both models (downloaded, registered in a local MLflow registry, prepared for TF Serving), then a check of the machine. It takes a few minutes and is safe to run again:

```bash
make install
```

It ends with the `make doctor` report: every line `ok` and the last one `Ready`. A `FAIL` line says how to fix it (see also [Troubleshooting](#troubleshooting)); fix it and run `make install` again. `WARN` lines only make things slower.

**2. Optional, a 1-minute check without Docker (dev mode).** The fast tests, then the app with a **fake** model that always finds one cat and counts kept only in memory (see [why dev mode isn't the real app](ARCHITECTURE.md#dev-or-prod-what-each-mode-really-runs)). The last line of the tests should say `... passed`:

```bash
make test
make run
```

In a second terminal (Windows: Start → type `Ubuntu` → Enter; Linux: **Ctrl+Alt+T**) send a picture. Expect `"class_name":"cat"` and `"version":null` (no real model):

```bash
cd ~/object-counter-demo
curl -F "file=@resources/images/cat.jpg" http://localhost:5000/object-predictions
```

Then press **Ctrl+C** in the first terminal.

**3. Start the real app:** the services (TF Serving with both models, MongoDB, PostgreSQL; the first time it downloads about 2.5 GB of images, about 5 minutes, later about 10 seconds), then the app. It ends with three `Healthy` lines and then keeps running, printing a line per request, so the prompt doesn't come back; **leave this terminal open**:

```bash
make start
```

On Windows the containers also appear in Docker Desktop under *Containers*.

**4. Try it** in the second terminal (open one as in step 2 if you closed it, and `cd ~/object-counter-demo`). Readiness should answer `"status":"ok"` for the repository and both models:

```bash
curl http://localhost:5000/health/ready
```

Count the objects in a sample picture. It answers with the objects found, the model that answered (`"version":"1"`, a real model) and the running totals; the first request per model takes about 5 seconds:

```bash
curl -F "threshold=0.5" -F "file=@resources/images/cat.jpg" http://localhost:5000/object-count
```

Without the command line: open [http://localhost:5000/docs](http://localhost:5000/docs) in your browser (on Windows too) → **POST /object-count** → **Try it out** → *file*: **Choose File** (any JPEG or PNG) → **Execute**.

**5. The full demo (optional).** Click into the **first** terminal and press **Ctrl+C** (the demo starts its own copy of the app, in a container, on the same port 5000). Then start everything in one command: the app, TF Serving and the databases in Docker, Prometheus and Grafana, demo data for the dashboards, and the MLflow UI in the background (the first time about 10 minutes; about 5.5 GB RAM). It ends by printing the address of every page, and the prompt comes back:

```bash
make demo
```

Add `REQUESTS=200` to also send 200 requests, so the traffic and latency panels have data. Without the demo data and the MLflow UI: `make monitoring`. The demo data replaces the drift baselines in `tmp/baselines/`; `make pull-models` brings the real ones back.

Open Grafana at [http://localhost:3000](http://localhost:3000) (no login needed to view; to edit, *Sign in* with `admin` / `admin`) → *Dashboards* → **Object Counter**, and Prometheus at [http://localhost:9090](http://localhost:9090) → *Status* → *Targets* (`object-counter` and `tfserving` *UP*).

Next: test every feature with [`TESTING-GUIDE.md`](TESTING-GUIDE.md).

## Part E: stop and start again

**Stop everything** (the counts stay saved in the databases):

1. If `make start` or `make run-prod` is running in a terminal, press **Ctrl+C** in it.
2. Stop the containers (and the MLflow UI, if `make demo` started it):

   ```bash
   cd ~/object-counter-demo
   make down
   ```

3. Windows, to free the memory: right-click the whale icon in the taskbar → **Quit Docker Desktop**.

**Start again next time** (Parts 0 to C and `make install` are only needed once):

1. Windows: start Docker Desktop (Start → type `Docker Desktop` → Enter) and wait for *Engine running*; then open the Ubuntu window. Linux: open a terminal.
2. Go into the folder and start the services and the app:

   ```bash
   cd ~/object-counter-demo
   make start
   ```

   Or, instead, the full demo with the dashboards: `make demo` (or `make monitoring`, without the demo data and the MLflow UI).

**Get the latest version of the code** (when the owner has changed it), with everything stopped. `make install` only installs or downloads what changed:

```bash
cd ~/object-counter-demo
git pull
make install
```

Then start again as above.

The timings were measured on an Ubuntu 26.04 VM with 2 CPUs and 5 GB RAM (2026-10-28).

## Troubleshooting

Run `make doctor` first; it catches most of these.

| Symptom | Cause / fix |
|---|---|
| `permission denied ... /var/run/docker.sock` | Not in the `docker` group yet: `sudo usermod -aG docker $USER`, then log out and in again |
| `docker: 'compose' is not a docker command` | Compose v2 missing: `sudo apt install -y docker-compose-v2` (the old `docker-compose` v1 isn't supported) |
| `make up`: `tfserving exited (255)`, log `NOT_FOUND: /models/model_config.config` | `tmp/model` is from an older pull: run `make pull-models` again |
| `ValueError: No pulled version for models ...` | The models aren't pulled yet: `make install`, then `make start` |
| `make monitoring` or `make demo`: `port 5000 ... address already in use` | `make start`, `make run-prod` or `make run` is still running; press Ctrl+C in its terminal, the app container takes its place |
| `python -m counter.entrypoints.drift` reports `without_baseline` | It ran with `ENV=dev` (empty in-memory log, unpinned `latest`); use `make drift`, which sets `ENV=prod` like `run-prod` |
| Drift gauges in Grafana show 0 images right after `make demo` or `make demo-data` | `/metrics` recomputes drift at most every `DRIFT_CACHE_SECONDS` (300 s); wait 5 minutes or lower it in `.env` |
| Windows: `docker: command not found` in Ubuntu | Docker Desktop isn't running, or *Settings → Resources → WSL integration → Ubuntu* is off; turn it on, then reopen the Ubuntu window |
| Windows: `wsl --install` fails or Docker Desktop says *WSL 2 is not installed* / *virtualization* | Enable virtualization in the BIOS/UEFI, run `wsl --update` in an administrator PowerShell, restart |
| Windows: everything very slow, or `permission denied` on files | The code is under `/mnt/c/...`; clone it again into the Ubuntu home folder (`cd ~`) |
| `git clone`: `Repository not found` or asks for a password | The repository is private: ask the owner for access, then `gh auth login` and `gh auth setup-git` |
| `make: command not found` | Part B step 1 |
| `503` `Read timed out` right after restarting TF Serving | It is still loading the models: wait until `/health/ready` says `ok` and send the request again |
| `make test-integration`: a test fails or many are skipped | Its throwaway database containers started too slowly (little RAM): `make down`, then run it again |
| `make monitoring` or `make demo` slow or containers restarting | Low RAM: check `free -m`; stop other containers or use `make start` without the monitoring stack |
| `make demo`: the MLflow page doesn't load | It needs about 25 seconds to start; if it still fails, read `tmp/mlflow-ui.log` (`make setup-models` if `.venv-models` is missing) |
| `make drift` reports drift everywhere after `make demo` | The demo data replaced the real baselines: `make pull-models` restores them |

