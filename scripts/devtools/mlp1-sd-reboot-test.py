#!/usr/bin/env python3
"""Power-cycle a backed-up MLP1 through menu IPC, checking its cards after each boot.

Writes only .userdata/mlp1/sd-safety-test/canary.bin on each mounted card.
Requires --execute. Stops on a refused reboot, build change, missing/read-only
card, kernel filesystem error, or changed test data. It never forces a reboot.
Offline fsck and save hashes before/after the run remain separate checks.
With --action poweroff, an operator must turn the handheld on after each shutdown.
--cards 1 qualifies the single-card layout and fails if a second card is mounted.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import time

LEAF = Path(__file__).resolve().parents[2]
SOCKET = '/tmp/jawaka-runtime/jawakad.sock'
CANARY = '.userdata/mlp1/sd-safety-test/canary.bin'
MLP1_MODEL = 'RK3566 RK817 MANGMI'
ERROR = re.compile(r'FAT-fs .*?(?:error|not properly unmounted|read-only)|I/O error|Buffer I/O', re.I)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute', action='store_true', help='authorize writes and menu-path reboots on backed-up cards')
    parser.add_argument('--cycles', type=int, default=1)
    parser.add_argument('--action', choices=('reboot', 'poweroff'), default='reboot')
    parser.add_argument('--cards', type=int, choices=(1, 2), default=2,
                        help='expected card layout; 1 requires the secondary slot to be empty')
    parser.add_argument('--serial', default=os.environ.get('ADB_SERIAL'))
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    if not args.execute or not 1 <= args.cycles <= 100:
        parser.error('--execute and 1..100 cycles are required')
    def model(serial):
        result = subprocess.run(['adb', '-s', serial, 'shell', 'cat /proc/device-tree/model'],
                                capture_output=True, text=True, timeout=10)
        return result.stdout if result.returncode == 0 else ''

    # Serials do not identify an MLP1 and other devices share the hub.
    if not args.serial:
        listing = subprocess.check_output(['adb', 'devices'], text=True)
        args.serial = next((row.split()[0] for row in listing.splitlines()[1:]
                            if len(row.split()) == 2 and row.split()[1] == 'device'
                            and MLP1_MODEL in model(row.split()[0])), None)
    if not args.serial:
        parser.error('no online MLP1 over ADB')
    if MLP1_MODEL not in model(args.serial):
        parser.error(f'{args.serial} is not an MLP1')
    adb = ['adb', '-s', args.serial]
    args.out.mkdir(parents=True, exist_ok=True)

    def run(*argv, timeout=20):
        result = subprocess.run(adb + list(argv), capture_output=True, text=True, timeout=timeout)
        if result.returncode:
            raise RuntimeError(result.stderr.strip() or result.stdout.strip())
        return result.stdout.strip()

    def shell(command):
        return run('shell', command)

    def snapshot():
        root = subprocess.check_output(
            [str(LEAF / 'scripts/adb-resolve-umrk-sd.sh')],
            env=dict(os.environ, ADB_SERIAL=args.serial, REMOTE_SDCARD_PATH='auto', PLATFORM_ID='mlp1'),
            stderr=subprocess.DEVNULL, text=True, timeout=10).strip()
        ctl = root + '/.system/leaf/platforms/mlp1/launcher/bin/jawaka-platformctl'
        prefix = shlex.quote(ctl) + ' --socket ' + SOCKET + ' request '
        cards = [json.loads(shell(prefix + shlex.quote(json.dumps({'type': 'storage-status', 'source': source}))))
                 for source in ('launcher_sd', 'secondary_sd')]
        if args.cards == 1:
            if cards[1].get('mounted'):
                raise RuntimeError('single-card run, but a secondary card is mounted: ' + json.dumps(cards[1]))
            cards = cards[:1]
        for card in cards:
            if not card.get('mounted') or card.get('access') != 'read-write' or card.get('repair') != 'none':
                raise RuntimeError('card is not safely writable: ' + json.dumps(card))
        if len({c.get('uuid') for c in cards}) != args.cards or any(not c.get('uuid') for c in cards):
            raise RuntimeError(f'{args.cards} distinct card UUID(s) are required')
        # Mount roots come from the daemon's source status, not a remembered slot.
        roots = [card['mount_path'] for card in cards]
        digest = shell('sha256sum ' + shlex.quote(root + '/.system/leaf/platforms/mlp1/launcher/bin/loong_pangu') +
                       ' /usr/bin/umrk-leaf-session /usr/bin/umrk-power-transition /usr/bin/umrk-storage-repair')
        return dict(boot=shell('cat /proc/sys/kernel/random/boot_id'), cards=cards,
                    roots=roots, hashes=[line.split()[0] for line in digest.splitlines()], prefix=prefix)

    current = snapshot()
    expected_hashes = current['hashes']
    (args.out / 'initial.json').write_text(json.dumps(current, indent=2) + '\n')
    payload = args.out / 'canary.bin'
    for cycle in range(1, args.cycles + 1):
        record = {'cycle': cycle, 'before': current}
        (args.out / f'cycle-{cycle:03d}.json').write_text(json.dumps(record, indent=2) + '\n')
        data = (f'Leaf SD safety cycle {cycle:03d}\n'.encode() * 50000)[:1024 * 1024]
        payload.write_bytes(data)
        expected = hashlib.sha256(data).hexdigest()
        for root in current['roots']:
            target = root + '/' + CANARY
            shell('mkdir -p ' + shlex.quote(str(Path(target).parent)))
            run('push', str(payload), target + '.pending')
            shell('mv -f ' + shlex.quote(target + '.pending') + ' ' + shlex.quote(target))
        start = time.monotonic()
        response = json.loads(shell(current['prefix'] + shlex.quote(json.dumps({'type': 'platform-action', 'action': args.action}))))
        if response.get('code') != 'ok':
            raise RuntimeError('power action refused: ' + json.dumps(response))
        record['reply'] = response
        (args.out / f'cycle-{cycle:03d}.json').write_text(json.dumps(record, indent=2) + '\n')
        deadline = start + 180
        while time.monotonic() < deadline:
            try:
                boot = shell('cat /proc/sys/kernel/random/boot_id; test -S ' + SOCKET)
                if boot != current['boot']:
                    next_state = snapshot()
                    break
            except (RuntimeError, subprocess.SubprocessError, KeyError, ValueError):
                pass  # disconnected or still starting; this never triggers another reboot
            time.sleep(2)
        else:
            raise RuntimeError('new boot did not complete; inspect /run/umrk-power-transition.log')
        if next_state['hashes'] != expected_hashes:
            raise RuntimeError('the deployed build changed during the test')
        if {c['uuid'] for c in current['cards']} != {c['uuid'] for c in next_state['cards']}:
            raise RuntimeError('card identity changed during the test')
        for root in next_state['roots']:
            actual = shell('sha256sum ' + shlex.quote(root + '/' + CANARY)).split()[0]
            if actual != expected:
                raise RuntimeError('test data changed on ' + root)
        dmesg = shell('dmesg')
        (args.out / f'cycle-{cycle:03d}.dmesg').write_text(dmesg + '\n')
        errors = [line for line in dmesg.splitlines() if ERROR.search(line)]
        record.update(after=next_state, elapsed_s=round(time.monotonic() - start, 2),
                      canary_sha256=expected, errors=errors)
        (args.out / f'cycle-{cycle:03d}.json').write_text(json.dumps(record, indent=2) + '\n')
        if errors:
            raise RuntimeError('kernel storage errors: ' + '\n'.join(errors))
        print(f"PASS {cycle}/{args.cycles}: {record['elapsed_s']}s; {args.cards} card(s) writable, test data intact", flush=True)
        current = next_state
    print('Power cycles passed. Run offline checks and compare save hashes before removing the dedicated test files.', flush=True)


if __name__ == '__main__':
    main()
