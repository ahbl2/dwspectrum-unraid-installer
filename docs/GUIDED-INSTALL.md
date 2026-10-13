# Guided install — development candidate

This is a **terminal-based guided installer**, not yet a point-and-click Unraid WebGUI
wizard and not a certified reinstall procedure. Run only on a *new or disposable*
Unraid host; existing DW deployments are explicitly refused.

Use the public repository to retrieve this reviewed source (the installation
source itself must be pinned to a known commit for production qualification).
No hosted prebuilt vendor image is provided.

```bash
python3 scripts/guided-install.py plan
python3 scripts/guided-install.py doctor
python3 scripts/guided-install.py install --apply
python3 scripts/guided-install.py bootstrap --apply
# Complete administrator setup in official DW client.
python3 scripts/guided-install.py enroll --apply
python3 scripts/guided-install.py activate --apply
python3 scripts/guided-install.py verify --apply
```

`plan` does not require root and makes no changes; `doctor` checks Unraid,
Docker, existing services and dedicated storage availability without changing them.
Every action after `doctor` requires `--apply`, and the underlying installer
also requires interactive explicit confirmation for fresh provision. Activation
will refuse until credentials and view-only storage safeguards pass.

If provisioning completed but the subsequent installer was interrupted,
inspect the dedicated filesystem before invoking `resume --apply`.

**Limitations:** Clone/download authentication is no longer needed for this
public source. The installation still needs Docker, Python and btrfs prerequisites;
the official vendor installer must be reachable. Lab integration and cold-boot
validation of this exact frontend remain outstanding. Never run this on PlexAaron.
