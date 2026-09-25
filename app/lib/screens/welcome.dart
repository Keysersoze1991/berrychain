import 'package:flutter/material.dart';

import '../main.dart';
import 'common.dart';

/// First launch: make a wallet or bring one from a PC.
class WelcomeScreen extends StatelessWidget {
  const WelcomeScreen({super.key});

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: Palette.sea,
      body: SafeArea(
        child: Padding(
          padding: const EdgeInsets.all(24),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              const Spacer(),
              const Text('BERRYCHAIN', style: TextStyle(color: Palette.gold2, letterSpacing: 3, fontSize: 13, fontWeight: FontWeight.w600)),
              const SizedBox(height: 10),
              const Text('Letters that only one person can open.', style: TextStyle(color: Colors.white, fontSize: 30, fontWeight: FontWeight.w600, height: 1.1)),
              const SizedBox(height: 14),
              const Text(
                'Remember pen pals? A letter written to one person, carried a long way, opened by nobody else. BerryChain brings that back. Your letter is sealed on this phone, carried across the water by a crew that cannot read it, and opened only by the hand it was written for.',
                style: TextStyle(color: Color(0xFFA9BACC), fontSize: 15.5, height: 1.45),
              ),
              const SizedBox(height: 10),
              const Text(
                'Hold BERRY, claim your starter, write and reply. Your keys never leave this phone.',
                style: TextStyle(color: Color(0xFFA9BACC), fontSize: 15.5, height: 1.45),
              ),
              const Spacer(),
              FilledButton(
                style: FilledButton.styleFrom(backgroundColor: Palette.gold, foregroundColor: Palette.sea),
                onPressed: () => Navigator.push(context, MaterialPageRoute(builder: (_) => const CreateWalletScreen())),
                child: const Text('Create a new wallet'),
              ),
              const SizedBox(height: 10),
              OutlinedButton(
                style: OutlinedButton.styleFrom(foregroundColor: Colors.white, side: const BorderSide(color: Color(0x73EEF3F8))),
                onPressed: () => Navigator.push(context, MaterialPageRoute(builder: (_) => const ImportWalletScreen())),
                child: const Text('Import a wallet file'),
              ),
              const SizedBox(height: 8),
              const Text('version $appVersion', textAlign: TextAlign.center, style: TextStyle(color: Color(0x80A9BACC), fontSize: 12)),
            ],
          ),
        ),
      ),
    );
  }
}

class CreateWalletScreen extends StatefulWidget {
  const CreateWalletScreen({super.key});
  @override
  State<CreateWalletScreen> createState() => _CreateWalletScreenState();
}

class _CreateWalletScreenState extends State<CreateWalletScreen> {
  final name = TextEditingController();
  final p1 = TextEditingController(), p2 = TextEditingController();

  Future<void> create() async {
    if (p1.text.length < 8) return toast(context, 'Use a passphrase of at least 8 characters');
    if (p1.text != p2.text) return toast(context, 'The passphrases do not match');
    final s = SessionScope.of(context);
    final ok = await runBusy<bool>(context, 'Sealing your wallet…', () async { await s.createWallet(name.text.trim(), p1.text); return true; });
    if (ok != null && mounted) Navigator.of(context).popUntil((r) => r.isFirst);
  }

  @override
  Widget build(BuildContext context) => Scaffold(
        appBar: AppBar(title: const Text('New wallet')),
        body: ListView(
          padding: const EdgeInsets.all(20),
          children: [
            const Text('The wallet is one small file on this phone, sealed with a passphrase. Lose the passphrase and the coins are gone; nobody can reset it.', style: TextStyle(height: 1.4)),
            const SizedBox(height: 18),
            TextField(controller: name, decoration: const InputDecoration(labelText: 'A name for this wallet (optional)')),
            const SizedBox(height: 12),
            PassphraseField(controller: p1, label: 'Passphrase'),
            const SizedBox(height: 12),
            PassphraseField(controller: p2, label: 'Passphrase again', onSubmitted: (_) => create()),
            const SizedBox(height: 20),
            FilledButton(onPressed: create, child: const Text('Create wallet')),
            const SizedBox(height: 12),
            const Text('Write the passphrase on paper and keep it somewhere other than with the phone.', style: TextStyle(color: Color(0xFF6F7883))),
          ],
        ),
      );
}

class ImportWalletScreen extends StatefulWidget {
  const ImportWalletScreen({super.key});
  @override
  State<ImportWalletScreen> createState() => _ImportWalletScreenState();
}

class _ImportWalletScreenState extends State<ImportWalletScreen> {
  final json = TextEditingController(), pass = TextEditingController();

  Future<void> import() async {
    if (pass.text.isEmpty) return toast(context, 'Enter the wallet passphrase');
    final s = SessionScope.of(context);
    final ok = await runBusy<bool>(context, 'Opening the wallet…', () async { await s.importWallet(json.text.trim(), pass.text); return true; });
    if (ok != null && mounted) Navigator.of(context).popUntil((r) => r.isFirst);
  }

  @override
  Widget build(BuildContext context) => Scaffold(
        appBar: AppBar(title: const Text('Import a wallet')),
        body: ListView(
          padding: const EdgeInsets.all(20),
          children: [
            const Text('Paste the contents of a wallet file made on a PC (keys\\savings.json, for example). The same file works on both. A plain, unsealed file will be sealed with the passphrase you enter here.', style: TextStyle(height: 1.4)),
            const SizedBox(height: 18),
            TextField(controller: json, maxLines: 8, decoration: const InputDecoration(labelText: 'Wallet file contents'), style: const TextStyle(fontFamily: 'monospace', fontSize: 12)),
            const SizedBox(height: 12),
            PassphraseField(controller: pass, label: 'Its passphrase', onSubmitted: (_) => import()),
            const SizedBox(height: 20),
            FilledButton(onPressed: import, child: const Text('Import')),
          ],
        ),
      );
}
