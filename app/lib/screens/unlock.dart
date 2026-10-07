import 'package:flutter/material.dart';
import 'package:flutter_svg/flutter_svg.dart';

import '../biometric.dart';
import '../main.dart';
import 'common.dart';

/// Passphrase unlock, with a quick-unlock button when Face ID, Touch ID or a
/// fingerprint has been switched on in Settings. A failed or cancelled
/// biometric check falls back to the passphrase, nothing else.
class UnlockScreen extends StatefulWidget {
  const UnlockScreen({super.key});
  @override
  State<UnlockScreen> createState() => _UnlockScreenState();
}

class _UnlockScreenState extends State<UnlockScreen> {
  final pass = TextEditingController();
  final bio = BiometricUnlock();
  bool quick = false;
  String quickLabel = 'Face ID';
  bool triedQuick = false;

  @override
  void initState() {
    super.initState();
    _prepareQuick();
  }

  Future<void> _prepareQuick() async {
    final on = await bio.enabled();
    if (!on || !mounted) return;
    final label = await bio.label();
    if (!mounted) return;
    setState(() {
      quick = true;
      quickLabel = label;
    });
    // Offer it straight away, once; the passphrase field stays underneath.
    if (!triedQuick) {
      triedQuick = true;
      await quickUnlock();
    }
  }

  Future<void> unlock() async {
    final s = SessionScope.of(context);
    await runBusy(context, 'Unlocking…', () => s.unlock(pass.text));
  }

  Future<void> quickUnlock() async {
    final s = SessionScope.of(context);
    final p = await bio.passphrase();
    if (p == null || !mounted) return;
    try {
      await runBusy(context, 'Unlocking…', () => s.unlock(p));
    } catch (_) {
      // The stored passphrase no longer opens this chest (it was changed on
      // another phone, or the file was replaced): drop quick unlock and ask.
      await bio.disable();
      if (mounted) {
        setState(() => quick = false);
        toast(context, 'Quick unlock no longer matches this chest. Enter the passphrase.');
      }
    }
  }

  @override
  Widget build(BuildContext context) => Scaffold(
        backgroundColor: Palette.sea,
        body: SafeArea(
          child: Padding(
            padding: const EdgeInsets.all(24),
            child: Column(
              mainAxisAlignment: MainAxisAlignment.center,
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                const Text('BERRYCHAIN', style: TextStyle(color: Palette.gold2, letterSpacing: 3, fontSize: 13, fontWeight: FontWeight.w600)),
                const SizedBox(height: 8),
                Row(children: [SvgPicture.asset('assets/icons/chest.svg', height: 30), const SizedBox(width: 10), const Text('Unlock your chest', style: TextStyle(color: Colors.white, fontSize: 28, fontWeight: FontWeight.w600))]),
                const SizedBox(height: 20),
                Theme(
                  data: Theme.of(context).copyWith(inputDecorationTheme: const InputDecorationTheme(border: OutlineInputBorder(), filled: true, fillColor: Colors.white)),
                  child: PassphraseField(controller: pass, onSubmitted: (_) => unlock()),
                ),
                const SizedBox(height: 16),
                FilledButton(style: FilledButton.styleFrom(backgroundColor: Palette.gold, foregroundColor: Palette.sea), onPressed: unlock, child: const Text('Unlock')),
                if (quick) ...[
                  const SizedBox(height: 10),
                  OutlinedButton.icon(
                    style: OutlinedButton.styleFrom(foregroundColor: Colors.white, side: const BorderSide(color: Colors.white54)),
                    icon: Icon(quickLabel.startsWith('Face') || quickLabel == 'face unlock' ? Icons.face : Icons.fingerprint),
                    label: Text('Unlock with $quickLabel'),
                    onPressed: quickUnlock,
                  ),
                ],
              ],
            ),
          ),
        ),
      );
}
