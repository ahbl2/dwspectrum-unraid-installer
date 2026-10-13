# Stop Array concurrency qualification (blocking)

Status: **NOT QUALIFIED**. Applies to draft PR #9 only. No production deployment.

## Verified observations
- Guarded startup mounts under the same `dwspectrum-config-operation.lock` as backup and Stop Array.
- Stop Array currently waits without a deadline. A hung child command may hold the operation lock indefinitely.
- Restoring a finite wait followed by exit would leave the ext4 quarantine mounted, potentially preventing array shutdown.
- The disposable Unraid VM currently runs older installed startup/shutdown scripts, including a non-executable persistent stop hook and missing volatile array-stop handler. Unit-test success is not a live Stop Array pass.

## Required design invariants
1. Establish shutdown intent atomically ahead of any startup admission. While it is set, both boot and manual guarded starts fail before mounting; backups must not begin. Only an explicitly verified array-up recovery path can remove it.
2. Bound all startup and backup work as complete process groups, including Docker calls, API audits, mount checks and archive verification. Track the exact operation identity; never kill arbitrary processes found by PID or lock listing.
3. Prevent lock descriptor leakage to descendants. A canceled operation must release the lock and leave no detached descendant able to mount or start Docker.
4. Stop Array must wait a bounded interval, then cancel only the owned operation, verify it has terminated and reacquire the lock. It must never continue cleanup while a writer is active or return apparent success with a mounted quarantine.
5. Hold exclusive protection from stopping the DW container through checking the loop backing path, unmounting, detaching residual loops and final verification. Log a critical, actionable failure if cleanup cannot complete.
6. Respect deliberate manual stops. Never auto-restart the container, force detach a busy or foreign loop, remove persistent data, or relax Compose restrictions.

## Mandatory regression and lab qualification
- Concurrent manual start vs Stop Array (including after mount but before Docker startup)
- Concurrent boot start vs Stop Array
- Concurrent backup vs Stop Array
- Hung Docker client, API audit, tar, and non-exiting child holding inherited FDs
- Bounded cancellation and shutdown-in-progress start refusal
- Mismatched/foreign loop device, failed unmount, and failed Docker stop
- Real disposable-VM Stop Array followed by array start and guarded recovery; verify ext4 loop absent during array stop and recording remains denied after recovery

This document records acceptance criteria, **not evidence of passing**. Keep PR draft and block merge/deployment until all relevant checks pass and independent review is complete.
