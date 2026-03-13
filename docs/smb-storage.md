# NAS / Network Storage Mounting Guide

Jyzrox reads local galleries via bind mounts. If your galleries are stored on a NAS or network storage device, you must first mount the share on the **host machine**, then let Docker containers access it through the `./mnt` bind mount.

## Overview

```
NAS / Network Drive
       │
       │  CIFS / NFS
       ▼
Host   /mnt/nas-share      ← You mount here
       │
       │  Docker bind mount  (./mnt:/mnt:ro)
       ▼
Container /mnt/nas-share    ← Jyzrox reads from here
       │
       │  library_base_path = "/mnt"
       ▼
Jyzrox UI → Settings → Library Path → /mnt/nas-share
```

Four services (`nginx`, `api`, `worker`, `tagger`) all mount `./mnt:/mnt:ro`. As long as the host's `/mnt/nas-share` is properly mounted, all four containers can access it simultaneously.

---

## Approach Comparison

| Approach | Stability | Reconnection | Security | Debugging | Recommendation |
|----------|-----------|-------------|----------|-----------|----------------|
| **Host Mount + Bind (recommended)** | High | Handled by systemd | Credentials file chmod 600 | Standard Linux tools | **Recommended** |
| Docker CIFS Volume | Low | No auto-reconnect | Password in plaintext in compose | Difficult | Not recommended |
| In-container mount | Low | Not viable | Requires CAP_SYS_ADMIN | Difficult | Do not use |

---

## Approaches to Avoid

### Docker CIFS Volume (`driver: local` + `type: cifs`)

Seems convenient, but has serious known issues:

- **No auto-reconnect**: After a NAS reboot or network interruption, containers see a stale mount. The only fix is recreating containers ([moby/moby#47184](https://github.com/moby/moby/issues/47184), [moby/moby#42007](https://github.com/moby/moby/issues/42007))
- **Boot race condition**: Docker daemon may attempt to mount before the network or NAS is ready, causing startup failures ([docker/for-win#15001](https://github.com/docker/for-win/issues/15001))
- **Plaintext password**: The `o: "username=...,password=..."` in `docker-compose.yml` is visible via `docker inspect` or `git diff`

### In-Container Mount

Running `mount` inside a container entrypoint requires `CAP_SYS_ADMIN`. The `docker-compose.yml` explicitly sets:

```yaml
security_opt: ["no-new-privileges:true"]
```

Combined with restricted Linux capabilities by default, this approach is not viable.

---

## NFS vs CIFS

If your NAS supports both NFS and SMB, **prefer NFS**.

| | NFS | CIFS (SMB) |
|---|-----|------------|
| Small file random reads | Better | Average |
| Reconnection | Controllable via `soft` + `timeo` | Harder to control |
| Linux tooling | Native | Requires `cifs-utils` |
| NAS setup complexity | Slightly higher (export squash config) | Simpler |
| Windows compatibility | N/A | Supported |

Synology / QNAP / TrueNAS all support NFS, though it may be disabled by default. If your NAS supports it, enable NFS.

---

## CIFS Mount Steps (Host-Level)

### Step 1: Install cifs-utils

```bash
# Debian / Ubuntu
sudo apt install cifs-utils

# Arch Linux
sudo pacman -S cifs-utils

# RHEL / Rocky / AlmaLinux
sudo dnf install cifs-utils
```

### Step 2: Create a credentials file

> ⚠️ Do not put credentials directly in `/etc/fstab`. A credentials file is the standard practice, keeping passwords out of any diffs or `ps` output.

```bash
sudo tee /root/.smb-credentials-nas << 'EOF'
username=your_nas_user
password=your_nas_password
domain=WORKGROUP
EOF
sudo chmod 600 /root/.smb-credentials-nas
```

If unsure about the `domain`, use `WORKGROUP` (default for Synology / QNAP).

### Step 3: Create the mount point

```bash
sudo mkdir -p /mnt/nas-share
```

### Step 4: Configure /etc/fstab

> ⚠️ **You MUST include `nofail` and `x-systemd.automount`.** Without these options, the system will hang at boot waiting for the mount if the NAS is offline or the network is not ready, potentially making the system unbootable.

Append to `/etc/fstab`:

```fstab
//192.168.1.100/media  /mnt/nas-share  cifs  noauto,x-systemd.automount,_netdev,x-systemd.requires=network-online.target,x-systemd.mount-timeout=30,nofail,credentials=/root/.smb-credentials-nas,uid=1042,gid=1042,ro,cache=strict,actimeo=60,vers=3.1.1  0  0
```

Replace `192.168.1.100` with your NAS IP and `media` with the actual share name.

**Option reference:**

| Option | Description |
|--------|-------------|
| `noauto,x-systemd.automount` | Lazy mount: only mounts on first access, preventing boot-time blocking |
| `_netdev` | Marks device as network-dependent; systemd waits for network before attempting mount |
| `x-systemd.requires=network-online.target` | Explicitly waits for full network readiness (including DHCP) |
| `x-systemd.mount-timeout=30` | Mount attempt times out after 30 seconds instead of hanging indefinitely |
| `nofail` | Mount failure does not block boot; system starts normally |
| `credentials=...` | Reads credentials from a file with 600 permissions |
| `uid=1042,gid=1042` | Matches the container's `appuser`, ensuring correct file permissions |
| `ro` | Read-only mount; Jyzrox only reads library files, no writes needed |
| `cache=strict,actimeo=60` | Aggressive metadata caching, reduces frequent queries to the NAS |
| `vers=3.1.1` | Uses SMB 3.1.1 (best security and performance); fall back to `3.0` or `2.1` if unsupported |

### Step 5: Test the mount

```bash
sudo systemctl daemon-reload
sudo mount /mnt/nas-share
ls -la /mnt/nas-share
```

Verify that you can see files on the NAS and that the owner shows `1042:1042` (or the corresponding username).

If mounting fails, check detailed errors:

```bash
dmesg | grep -i cifs | tail -20
journalctl -u $(systemd-escape --path /mnt/nas-share).mount --since "5 min ago"
```

### Step 6: Integrate with Jyzrox

There are two ways to expose the mounted path to Jyzrox containers. Choose one.

**Method A: Symlink (recommended, no compose changes needed)**

```bash
# Run from the Jyzrox project directory
ln -s /mnt/nas-share ./mnt/nas-share
```

The containers can then access it via `/mnt/nas-share`.

**Method B: docker-compose.override.yml**

Add extra volume mounts for the services that need access in `docker-compose.override.yml`:

```yaml
services:
  nginx:
    volumes:
      - /mnt/nas-share:/mnt/nas:ro
  api:
    volumes:
      - /mnt/nas-share:/mnt/nas:ro
  worker:
    volumes:
      - /mnt/nas-share:/mnt/nas:ro
```

> ⚠️ If you have `tagger` enabled, add the corresponding volume to the `tagger` service as well, otherwise AI tagging cannot read images from the NAS.

Restart services:

```bash
docker compose up -d
```

Then in the Jyzrox UI: **Settings → Library → Add Path** → enter `/mnt/nas-share` (or `/mnt/nas`, depending on your chosen method).

### Step 7: Verify disconnection recovery

1. Shut down the NAS or disconnect the network cable
2. Verify the host still operates normally (SSH should work)
3. Try `ls /mnt/nas-share`: expect a timeout error or empty directory, **not a system hang**
4. Power the NAS back on and wait for it to come online
5. Run `ls /mnt/nas-share` again — it should recover automatically (x-systemd.automount retries)
6. Open Jyzrox and confirm the library is browsable

---

## NFS Mount Steps (Host-Level)

### Step 1: Install nfs-common

```bash
# Debian / Ubuntu
sudo apt install nfs-common

# Arch Linux
sudo pacman -S nfs-utils

# RHEL / Rocky
sudo dnf install nfs-utils
```

### Step 2: Configure NFS Export on the NAS

The NAS must export the shared folder to the host's IP with UID squash configured.

**Synology DSM**: Control Panel → File Services → NFS → Edit Folder → Add Rule:

```
Host or IP: 192.168.1.0/24 (or specific host IP)
Permission: Read-only
Squash: All squash
UID: 1042
GID: 1042
```

**TrueNAS** (using `/etc/exports` format):

```
/mnt/pool/media  192.168.1.50(ro,all_squash,anonuid=1042,anongid=1042,no_subtree_check)
```

Replace `192.168.1.50` with your Docker host IP.

### Step 3: Create the mount point

```bash
sudo mkdir -p /mnt/nas-share
```

### Step 4: Configure /etc/fstab

```fstab
192.168.1.100:/volume1/media  /mnt/nas-share  nfs  noauto,x-systemd.automount,_netdev,x-systemd.requires=network-online.target,x-systemd.mount-timeout=30,nofail,ro,soft,timeo=30,retrans=3,rsize=1048576,noatime,vers=4.1  0  0
```

**NFS-specific option reference:**

| Option | Description |
|--------|-------------|
| `soft` | Returns an error after NFS request timeout instead of retrying indefinitely (prevents I/O hangs) |
| `timeo=30` | Timeout of 3 seconds (unit is 0.1s, so 30 = 3s) |
| `retrans=3` | Maximum 3 retries before giving up |
| `rsize=1048576` | Read block size of 1MB, better performance for large galleries |
| `noatime` | Disables access time updates, reducing writes to the NAS |
| `vers=4.1` | NFSv4.1, supports session trunking for better reconnection |

### Step 5: Test the mount

```bash
sudo systemctl daemon-reload
sudo mount /mnt/nas-share
ls -la /mnt/nas-share
```

Verify the file owner shows `1042:1042` (determined by the NAS-side `all_squash,anonuid=1042` setting).

### Step 6: Integrate with Jyzrox

Same steps as CIFS — see [Step 6](#step-6-integrate-with-jyzrox) above.

---

## Common NAS Configuration

### Synology DSM

**Enable SMB:**
Control Panel → File Services → SMB → Enable SMB service

**Enable NFS:**
Control Panel → File Services → NFS → Enable NFS service

**Shared folder permissions (SMB):**
Control Panel → Shared Folder → Edit → Local Users → Set read permission for your account

**UID 1042 mapping (NFS):**
NFS UID squash settings are under "Shared Folder → NFS Permissions" — set `anonuid=1042,anongid=1042`.

### QNAP QTS

**Enable SMB:**
Control Panel → Network & File Services → Win/Mac/NFS → Microsoft Networking

**Enable NFS:**
Control Panel → Network & File Services → Win/Mac/NFS → NFS Service

NFS permissions for shared folders are configured under "Shared Folder → Edit → NFS Host Access".

### TrueNAS CORE / SCALE

NFS is a native feature on TrueNAS — prefer it over SMB.

Storage → Shares → Unix Shares (NFS) → Add:
- Path: Select the dataset to share
- Advanced Options → `mapall User` / `mapall Group`: Enter the user corresponding to UID 1042 (or create a user with uid=1042)

---

## Performance Tuning

| Tuning Point | Recommendation | Description |
|--------------|----------------|-------------|
| `actimeo=60` (CIFS) | 60–300 seconds | Galleries are static content; aggressive metadata caching significantly reduces NAS queries |
| `rsize=1048576` (NFS) | 1MB | Improves read throughput for large images |
| `noatime` (NFS) | Enable | Read-only mounts should not update access times anyway |
| Thumbnail cache | Keep on app_data volume | Jyzrox thumbnails live in `/data/thumbs/` (`app_data` volume), already on local SSD, unaffected by NAS speed |
| SMB version | `vers=3.1.1` | Better read performance and encryption than 2.1 |
| NFS version | `vers=4.1` | Better reconnection than v3 |

---

## Troubleshooting

### mount: permission denied

```bash
# Verify credentials file content
sudo cat /root/.smb-credentials-nas

# Verify the NAS share name exists
smbclient -L //192.168.1.100 -U your_nas_user

# Verify the NAS allows access from this IP (check NAS admin interface allow list)
```

### System hangs at boot during mounting

Missing `nofail` and `x-systemd.automount` in fstab. Edit `/etc/fstab` to add these options, then:

```bash
sudo systemctl daemon-reload
```

If the system is already stuck, enter recovery mode or use a console to edit fstab.

### Jyzrox shows I/O errors / images fail to load

The NAS may be offline or reconnecting. Check the host mount status:

```bash
# CIFS
dmesg | grep cifs | tail -20

# NFS
dmesg | grep nfs | tail -20

# Check if the mount is responsive
timeout 5 ls /mnt/nas-share && echo "OK" || echo "TIMEOUT / ERROR"
```

If the mount is stale, force a remount:

```bash
sudo umount -l /mnt/nas-share
sudo mount /mnt/nas-share
```

### File owner shows nobody / nogroup

UID mapping is incorrect. Verify in fstab:

- CIFS: `uid=1042,gid=1042` is present
- NFS: `anonuid=1042,anongid=1042` is set on the NAS side, and `all_squash` is enabled

After remounting, verify:

```bash
ls -ln /mnt/nas-share | head -5
# Should show 1042 1042
```

### CIFS version negotiation failure

Some older NAS devices do not support SMB 3.1.1. Error message looks like `CIFS VFS: SMB2 SERVER_MESSAGE_BLOCK v3.1.1 not supported`. Try downgrading:

```
vers=3.0
```

Or:

```
vers=2.1
```

### NFS mount reads are slow

Verify `rsize` is correctly set and that the NAS is not throttling. Test actual read speed:

```bash
dd if=/mnt/nas-share/test-large-file of=/dev/null bs=1M status=progress
```
