import 'package:flutter/material.dart';

import '../main.dart';
import 'common.dart';

class UnlockScreen extends StatefulWidget {
  const UnlockScreen({super.key});
  @override
  State<UnlockScreen> createState() => _UnlockScreenState();
}

class _UnlockScreenState extends State<UnlockScreen> {
  final pass = TextEditingController();

  Future<void> unlock() async {
    final s = SessionScope.of(context);
    await runBusy(context, 'Unlocking…', () => s.unlock(pass.text));
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
                const Text('Unlock your wallet', style: TextStyle(color: Colors.white, fontSize: 28, fontWeight: FontWeight.w600)),
                const SizedBox(height: 20),
                Theme(
                  data: Theme.of(context).copyWith(inputDecorationTheme: const InputDecorationTheme(border: OutlineInputBorder(), filled: true, fillColor: Colors.white)),
                  child: PassphraseField(controller: pass, onSubmitted: (_) => unlock()),
                ),
                const SizedBox(height: 16),
                FilledButton(style: FilledButton.styleFrom(backgroundColor: Palette.gold, foregroundColor: Palette.sea), onPressed: unlock, child: const Text('Unlock')),
              ],
            ),
          ),
        ),
      );
}
