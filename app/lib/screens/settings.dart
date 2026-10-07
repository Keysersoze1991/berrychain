import 'package:flutter/foundation.dart' show kIsWeb;
import 'package:flutter/material.dart';

import '../background.dart';
import '../biometric.dart';
import '../core/secure.dart';
import '../main.dart';
import '../push.dart';
import '../session.dart';
import 'package:flutter_svg/flutter_svg.dart';
import 'common.dart';
import 'welcome.dart';

/// The name letters are signed with: seen by the people you write to, never by the chain.
class NamePanel extends StatefulWidget {
  final Session s;
  const NamePanel(this.s, {super.key});
  @override
  State<NamePanel> createState() => _NamePanelState();
}

class _NamePanelState extends State<NamePanel> {
  late final ctl = TextEditingController(text: widget.s.wallet?.label ?? '');
  @override
  Widget build(BuildContext context) {
    final s = widget.s;
    final onChain = s.chainName;
    final canRename = s.registry != null && s.seatsLive;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Expanded(
              child: TextField(
                controller: ctl,
                decoration: InputDecoration(
                    labelText: 'Your name',
                    helperText: onChain == null
                        ? 'How your letters are signed. The people you write to see it; the chain does not.'
                        : 'How your letters are signed. Your name on the chain, the one people can write to, is "$onChain".',
                    helperMaxLines: 3),
              ),
            ),
            const SizedBox(width: 8),
            Padding(
              padding: const EdgeInsets.only(top: 6),
              child: FilledButton.tonal(
                onPressed: () async {
                  await s.setLabel(ctl.text);
                  if (context.mounted) toast(context, 'Saved. New letters are signed this way.');
                },
                child: const Text('Save'),
              ),
            ),
          ],
        ),
        if (canRename)
          Align(
            alignment: Alignment.centerLeft,
            child: TextButton.icon(
              icon: const Icon(Icons.badge_outlined, size: 18),
              label: const Text('Also change my name on the chain'),
              onPressed: () async {
                try {
                  await runBusy(context, 'Changing your name on the chain…', () => s.renameOnChain(ctl.text));
                  if (context.mounted) toast(context, 'Done. The chain shows "${ctl.text.trim()}" once the block is mined. One change a day.');
                } catch (e) {
                  if (context.mounted) toast(context, '$e'.replaceFirst(RegExp(r'^\w+Error: '), '').replaceFirst('Bad state: ', '').replaceFirst('Invalid argument(s): ', ''));
                }
              },
            ),
          ),
        if (s.registry != null && !s.seatsLive)
          Padding(
            padding: const EdgeInsets.only(top: 4),
            child: Text('Changing your name on the chain switches on at block ${formatCount(s.seatsActivation)}.', style: const TextStyle(fontSize: 12.5, color: Color(0xFF6F7883))),
          ),
      ],
    );
  }
}

/// Rotate, recover and burn receiving keys, with the consequences spelled out.
class KeysPanel extends StatelessWidget {
  final Session s;
  const KeysPanel(this.s, {super.key});

  Future<void> rotate(BuildContext context, bool backup) async {
    if (!backup && !await confirmPassphrase(context, s.confirmPassphrase, why: 'A key with no backup cannot be recovered by anyone. Your passphrase, not quick unlock, confirms this step.')) return;
    if (!context.mounted) return;
    final ok = await showDialog<bool>(
      context: context,
      builder: (_) => AlertDialog(
        title: Text(backup ? 'Rotate, backed up to your words' : 'Rotate with no backup'),
        content: Text(backup
            ? 'New letters will be sealed to a fresh key. Its private half rides in the rotation record, locked to your root key, so your twelve words restore it on any phone. Old letters stay readable. Costs one fee.'
            : 'New letters will be sealed to a fresh key that exists only on this phone. Your twelve words will NOT bring it back. If this phone is lost, or you burn the key later, every letter sealed to it is unreadable for good. Costs one fee.'),
        actions: [
          TextButton(onPressed: () => Navigator.pop(context, false), child: const Text('Cancel')),
          FilledButton(onPressed: () => Navigator.pop(context, true), child: Text(backup ? 'Rotate' : 'Rotate, no backup')),
        ],
      ),
    );
    if (ok != true || !context.mounted) return;
    final id = await runBusy(context, 'Publishing the new key…', () => s.rotateKey(backup: backup));
    if (id != null && context.mounted) toast(context, 'New receiving key published. The old one still takes letters for two hours.');
  }

  Future<void> burn(BuildContext context, String pub) async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (_) => AlertDialog(
        title: const Text('Burn this key?'),
        content: const Text('Every letter sealed to it becomes unreadable for good, on this phone and everywhere else, words or no words. This cannot be undone.'),
        actions: [
          TextButton(onPressed: () => Navigator.pop(context, false), child: const Text('Keep')),
          FilledButton(style: FilledButton.styleFrom(backgroundColor: Palette.band, foregroundColor: Colors.white), onPressed: () => Navigator.pop(context, true), child: const Text('Burn')),
        ],
      ),
    );
    if (ok == true) {
      final done = await s.burnKey(pub);
      if (context.mounted) toast(context, done ? 'Key burned.' : 'That key cannot be burned.');
    }
  }

  @override
  Widget build(BuildContext context) {
    final w = s.wallet;
    if (w == null) return const SizedBox.shrink();
    final live = s.rotationLive;
    final registered = s.registry != null;
    final held = s.holdsCurrentKey;
    final past = w.encKeys.keys.where((k) => k != w.encRootPub && k != w.encPub).toList();
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          !live
              ? 'Key rotation switches on at block ${formatCount(s.rotateActivation)}. Until then letters use the key your words derive.'
              : !registered
                  ? 'Claim your starter first; then you can rotate.'
                  : held
                      ? 'This phone holds ${w.encKeys.length} receiving key${w.encKeys.length == 1 ? '' : 's'} and can open every letter sealed to them. New letters go to the current one. The app rotates it about monthly, backed up to your words.'
                      : 'The key the chain says you receive on is not on this phone: it was rotated elsewhere without a backup. Rotate now so people seal to a key you hold.',
          style: TextStyle(height: 1.4, color: held ? null : Palette.band),
        ),
        const SizedBox(height: 10),
        Row(children: [
          Expanded(child: FilledButton.tonal(onPressed: live && registered ? () => rotate(context, true) : null, child: const Text('Rotate now'))),
          const SizedBox(width: 10),
          Expanded(child: OutlinedButton(onPressed: live && registered ? () => rotate(context, false) : null, child: const Text('Rotate, no backup'))),
        ]),
        const SizedBox(height: 6),
        TextButton.icon(
          icon: const Icon(Icons.cloud_download_outlined, size: 18),
          label: const Text('Recover rotated keys from the chain'),
          onPressed: !registered
              ? null
              : () async {
                  final r = await runBusy(context, 'Reading your rotations…', () => s.recoverKeys());
                  if (r != null && context.mounted) toast(context, '${r.$1.length} restored${r.$2.isNotEmpty ? ', ${r.$2.length} had no backup' : ''}');
                },
        ),
        if (past.isNotEmpty) ...[
          const SizedBox(height: 6),
          const Text('Past keys on this phone', style: TextStyle(fontWeight: FontWeight.w600)),
          for (final k in past)
            ListTile(
              contentPadding: EdgeInsets.zero,
              dense: true,
              title: Text('${k.substring(0, 12)}…', style: const TextStyle(fontFamily: 'monospace', fontSize: 12.5)),
              subtitle: Text(s.keyIsBackedUp(k) ? 'Backed up to your words; burning here would change nothing.' : 'Only on this phone. Burn it and its letters are gone for good.'),
              trailing: s.keyIsBackedUp(k) ? null : TextButton(onPressed: () => burn(context, k), child: const Text('Burn', style: TextStyle(color: Palette.band))),
            ),
        ],
      ],
    );
  }
}

class SettingsScreen extends StatefulWidget {
  const SettingsScreen({super.key});
  @override
  State<SettingsScreen> createState() => _SettingsScreenState();
}

class _SettingsScreenState extends State<SettingsScreen> {
  late final TextEditingController nodes;

  @override
  void initState() {
    super.initState();
    nodes = TextEditingController(text: SessionScope.of(context).nodeUrls.join('\n'));
  }

  @override
  Widget build(BuildContext context) {
    final s = SessionScope.of(context);
    return Scaffold(
      appBar: AppBar(title: const Text('Settings')),
      body: ListView(
        padding: const EdgeInsets.all(20),
        children: [
          const Text('NODES', style: TextStyle(fontSize: 11.5, letterSpacing: 1.2, fontWeight: FontWeight.w600, color: Color(0xFF6F7883))),
          const SizedBox(height: 6),
          TextField(controller: nodes, maxLines: 4, decoration: const InputDecoration(helperText: 'One URL per line. The first is used; the others cross-check it.'), style: const TextStyle(fontFamily: 'monospace', fontSize: 13)),
          const SizedBox(height: 10),
          OutlinedButton(
            onPressed: () async {
              await s.saveSettings(nodes.text.split('\n'));
              if (context.mounted) toast(context, 'Saved');
            },
            child: const Text('Save nodes'),
          ),
          TextButton(onPressed: () => setState(() => nodes.text = Network.seeds.join('\n')), child: const Text('Reset to the seed nodes')),
          const Divider(height: 32),
          const Text('LETTERS', style: TextStyle(fontSize: 11.5, letterSpacing: 1.2, fontWeight: FontWeight.w600, color: Color(0xFF6F7883))),
          if (isBrowser)
            const Padding(
              padding: EdgeInsets.symmetric(vertical: 8),
              child: Text('In the browser the letterbox is checked whenever this page is open. For a nudge when a letter arrives, install the phone app.', style: TextStyle(height: 1.4)),
            ),
          if (!isBrowser)
            TextButton.icon(
              icon: const Icon(Icons.notifications_active_outlined, size: 18),
              label: const Text('Show me a test notification, with sound'),
              onPressed: () async {
                await showTestNotification();
                if (context.mounted) toast(context, 'Sent. If nothing appeared, check BerryChain in the phone\'s notification settings.');
              },
            ),
          if (!isBrowser) ListenableBuilder(
            listenable: s,
            builder: (context, _) => SwitchListTile(
              contentPadding: EdgeInsets.zero,
              title: const Text('Tell me when a letter arrives'),
              subtitle: Text(pushSupported
                  ? 'Asks a seed node for new letters when the phone allows it. iPhone decides when that is, and never while the app is swiped away, so it can be hours; see the switch below for a nudge straight away.'
                  : 'Checks a seed node about every fifteen minutes, even with the app closed, and shows a badge. No server of ours is involved.'),
              value: s.backgroundChecks,
              onChanged: (v) => s.saveSettings(s.nodeUrls, background: v),
            ),
          ),
          if (pushSupported) ListenableBuilder(
            listenable: s,
            builder: (context, _) => SwitchListTile(
              contentPadding: EdgeInsets.zero,
              title: const Text('Tell me straight away'),
              subtitle: Text('A seed node sends an Apple push the moment a letter for you is carried in a block. To do that it keeps the pairing of this phone and your address until you switch this off; the push says a letter arrived and nothing else.'
                  '${s.pushError == null ? '' : '\n${s.pushError}'}'),
              value: s.instantNotices,
              onChanged: (v) async {
                try {
                  await s.setInstantNotices(v);
                  if (context.mounted) toast(context, v ? 'On. The seed will nudge this phone when a letter lands.' : 'Off. The seed has forgotten this phone.');
                } catch (e) {
                  if (context.mounted) toast(context, '$e'.replaceFirst(RegExp(r'^\w+Error: '), '').replaceFirst('Bad state: ', ''));
                }
              },
            ),
          ),
          ListenableBuilder(
            listenable: s,
            builder: (context, _) => SwitchListTile(
              contentPadding: EdgeInsets.zero,
              title: const Text('Show letters removed from this phone'),
              subtitle: Text('${s.removedCount == 0 ? 'Nothing removed yet.' : '${s.removedCount} removed; removing hides a letter here, and the sealed copy stays on the chain, readable only with its key.'}'
                  '${s.burnedCount > 0 ? ' ${s.burnedCount} burned: those never come back on this phone.' : ''}'),
              value: s.showRemoved,
              onChanged: (v) => s.setShowRemoved(v),
            ),
          ),
          const Divider(height: 32),
          const Text('RECEIVING KEYS', style: TextStyle(fontSize: 11.5, letterSpacing: 1.2, fontWeight: FontWeight.w600, color: Color(0xFF6F7883))),
          const SizedBox(height: 6),
          ListenableBuilder(listenable: s, builder: (context, _) => KeysPanel(s)),
          const Divider(height: 32),
          const Text('YOUR NAME', style: TextStyle(fontSize: 11.5, letterSpacing: 1.2, fontWeight: FontWeight.w600, color: Color(0xFF6F7883))),
          const SizedBox(height: 6),
          ListenableBuilder(listenable: s, builder: (context, _) => NamePanel(s)),
          const Divider(height: 32),
          if (!kIsWeb) ...[
            const Text('UNLOCKING', style: TextStyle(fontSize: 11.5, letterSpacing: 1.2, fontWeight: FontWeight.w600, color: Color(0xFF6F7883))),
            const SizedBox(height: 6),
            QuickUnlockPanel(s),
            const Divider(height: 32),
          ],
          Row(children: [SvgPicture.asset('assets/icons/chest.svg', height: 18), const SizedBox(width: 8), const Text('TREASURE CHEST', style: TextStyle(fontSize: 11.5, letterSpacing: 1.2, fontWeight: FontWeight.w600, color: Color(0xFF6F7883)))]),
          const SizedBox(height: 6),
          if (s.wallet?.mnemonic != null) ...[
            const Text('Your twelve recovery words rebuild this chest on any phone or PC. Show them only when nobody is looking over your shoulder.', style: TextStyle(height: 1.4)),
            const SizedBox(height: 10),
            OutlinedButton.icon(
              icon: const Icon(Icons.key_outlined),
              label: const Text('Show recovery phrase'),
              onPressed: () async {
                final ok = await showDialog<bool>(context: context, builder: (_) => AlertDialog(title: const Text('Show the words?'), content: const Text('Anyone who sees them can take the chest.'), actions: [TextButton(onPressed: () => Navigator.pop(context, false), child: const Text('Cancel')), FilledButton(onPressed: () => Navigator.pop(context, true), child: const Text('Show'))]));
                if (ok == true && context.mounted) Navigator.push(context, MaterialPageRoute(builder: (_) => ShowPhraseScreen(s.wallet!.mnemonic!)));
              },
            ),
            const SizedBox(height: 16),
          ] else ...[
            const Text('This chest was made before recovery phrases existed, so it has no words. Keep the exported file safe; it is the only way to move it to another phone.', style: TextStyle(height: 1.4, color: Palette.band)),
            const SizedBox(height: 10),
          ],
          const Text('Export copies the sealed chest file to the clipboard. Paste it into a text file on a PC and it opens there with the same passphrase. Keep a copy somewhere safe; without the file and the passphrase the coins are gone.', style: TextStyle(height: 1.4)),
          const SizedBox(height: 6),
          const Text('The file is sealed, but anything that reads the clipboard in the next minute gets a copy of it, and whoever has the file only needs your passphrase. Paste it straight into its destination.', style: TextStyle(fontSize: 12.5, color: Color(0xFF6F7883), height: 1.4)),
          const SizedBox(height: 10),
          OutlinedButton.icon(
            icon: const Icon(Icons.copy),
            label: const Text('Export sealed chest file'),
            onPressed: () async {
              if (!await confirmPassphrase(context, s.confirmPassphrase, why: 'Your passphrase, not quick unlock, confirms an export.')) return;
              final json = await s.exportWalletJson();
              final expires = await copySensitive(json);
              if (context.mounted) toast(context, kIsWeb ? 'Sealed chest copied. Paste it somewhere safe.' : expires ? 'Sealed chest copied. The clipboard forgets it after a minute.' : 'Sealed chest copied. It leaves the clipboard after a minute.');
            },
          ),
          const Divider(height: 32),
          Text('BerryChain $appVersion. Verified light client: pinned genesis and checkpoint, proof-of-work checked on every header. Pre-audit software; do not hold value you cannot afford to lose.', style: const TextStyle(color: Color(0xFF6F7883), fontSize: 13, height: 1.4)),
          const SizedBox(height: 6),
          const Text('berrychain.link', style: TextStyle(color: Palette.brass)),
        ],
      ),
    );
  }
}

/// Opt-in quick unlock with Face ID, Touch ID or a fingerprint. Turning it
/// on asks for the passphrase (so a borrowed, already-open phone cannot
/// enrol itself) and then the biometric check. The passphrase stays the
/// master and is still asked for on export and no-backup rotations.
class QuickUnlockPanel extends StatefulWidget {
  final Session s;
  const QuickUnlockPanel(this.s, {super.key});
  @override
  State<QuickUnlockPanel> createState() => _QuickUnlockPanelState();
}

class _QuickUnlockPanelState extends State<QuickUnlockPanel> {
  final bio = BiometricUnlock();
  bool? available;
  bool enabled = false;
  String label = 'Face ID';

  @override
  void initState() {
    super.initState();
    () async {
      final a = await bio.available();
      final e = await bio.enabled();
      final l = await bio.label();
      if (mounted) setState(() { available = a; enabled = e; label = l; });
    }();
  }

  Future<void> toggle(bool on) async {
    if (!on) {
      await bio.disable();
      if (mounted) setState(() => enabled = false);
      return;
    }
    final ok = await confirmPassphrase(context, widget.s.confirmPassphrase, why: 'Enter the passphrase once more. From then on $label opens the chest; the passphrase is still asked for when you export it or rotate a key with no backup.');
    if (!ok || !mounted) return;
    final p = widget.s.wallet?.passphrase;
    if (p == null || p.isEmpty) return;
    final done = await bio.enable(p);
    if (!mounted) return;
    setState(() => enabled = done);
    if (!done) toast(context, '$label did not confirm. Quick unlock stays off.');
  }

  @override
  Widget build(BuildContext context) {
    if (available == null) return const SizedBox(height: 24);
    if (available == false) {
      return Text(enabled
          ? 'Quick unlock is on, but this phone has no $label enrolled right now, so the passphrase is asked for.'
          : 'This phone has no face or fingerprint unlock set up, so the passphrase is the only way in. Set one up in the phone’s own settings and the switch appears here.',
          style: const TextStyle(fontSize: 13, color: Color(0xFF6F7883), height: 1.4));
    }
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      SwitchListTile(
        contentPadding: EdgeInsets.zero,
        title: Text('Unlock with $label'),
        subtitle: Text(enabled
            ? 'The chest opens with $label. The passphrase is still needed to export it or rotate a key with no backup, and whenever $label fails.'
            : 'Open the chest with $label instead of typing the passphrase. The passphrase stays the master key and is asked for again on the steps that can lose coins or letters.'),
        value: enabled,
        onChanged: toggle,
      ),
      Text('The passphrase is kept in the phone’s keychain, which only this app can read and only after the phone itself is unlocked. Anyone who can pass $label on this phone can open the chest, so keep it to your own face or finger.', style: TextStyle(fontSize: 12.5, color: Color(0xFF6F7883), height: 1.4)),
    ]);
  }
}
