import 'package:flutter/material.dart';

import '../core/mnemonic.dart';
import '../main.dart';
import 'common.dart';

/// First launch: make a wallet, recover one from its twelve words, or bring
/// a wallet file from a PC.
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
              const Spacer(),
              FilledButton(
                style: FilledButton.styleFrom(backgroundColor: Palette.gold, foregroundColor: Palette.sea),
                onPressed: () => Navigator.push(context, MaterialPageRoute(builder: (_) => const CreateWalletScreen())),
                child: const Text('Create a new wallet'),
              ),
              const SizedBox(height: 10),
              OutlinedButton(
                style: OutlinedButton.styleFrom(foregroundColor: Colors.white, side: const BorderSide(color: Color(0x73EEF3F8))),
                onPressed: () => Navigator.push(context, MaterialPageRoute(builder: (_) => const RecoverWalletScreen())),
                child: const Text('I already have a wallet'),
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
    final phrase = await runBusy<String>(context, 'Sealing your wallet…', () => s.createWallet(name.text.trim(), p1.text));
    if (phrase != null && mounted) {
      Navigator.pushReplacement(context, MaterialPageRoute(builder: (_) => ShowPhraseScreen(phrase, firstTime: true)));
    }
  }

  @override
  Widget build(BuildContext context) => Scaffold(
        appBar: AppBar(title: const Text('New wallet')),
        body: ListView(
          padding: const EdgeInsets.all(20),
          children: [
            const Text('The wallet lives on this phone, sealed with a passphrase you choose now. Next you will be shown twelve words: they rebuild the wallet on any phone or PC, so they matter more than the phone does.', style: TextStyle(height: 1.4)),
            const SizedBox(height: 18),
            TextField(controller: name, decoration: const InputDecoration(labelText: 'A name for this wallet (optional)')),
            const SizedBox(height: 12),
            PassphraseField(controller: p1, label: 'Passphrase for this phone'),
            const SizedBox(height: 12),
            PassphraseField(controller: p2, label: 'Passphrase again', onSubmitted: (_) => create()),
            const SizedBox(height: 20),
            FilledButton(onPressed: create, child: const Text('Create wallet')),
          ],
        ),
      );
}

/// The twelve words, shown once at creation and again from Settings.
class ShowPhraseScreen extends StatelessWidget {
  final String phrase;
  final bool firstTime;
  const ShowPhraseScreen(this.phrase, {super.key, this.firstTime = false});

  @override
  Widget build(BuildContext context) {
    final words = phrase.split(' ');
    return Scaffold(
      appBar: AppBar(title: const Text('Your recovery phrase'), automaticallyImplyLeading: !firstTime),
      body: ListView(
        padding: const EdgeInsets.all(20),
        children: [
          const Text('Write these twelve words on paper, in order, and keep them somewhere other than with the phone. Anyone with the words has the wallet; without them, a lost phone means lost coins and letters.', style: TextStyle(height: 1.4)),
          const SizedBox(height: 16),
          Card(
            child: Padding(
              padding: const EdgeInsets.all(16),
              child: GridView.count(
                crossAxisCount: 2,
                shrinkWrap: true,
                physics: const NeverScrollableScrollPhysics(),
                childAspectRatio: 4.2,
                children: [
                  for (var i = 0; i < words.length; i++)
                    Row(children: [
                      SizedBox(width: 28, child: Text('${i + 1}.', style: const TextStyle(color: Color(0xFF6F7883)))),
                      Text(words[i], style: const TextStyle(fontSize: 17, fontWeight: FontWeight.w600)),
                    ]),
                ],
              ),
            ),
          ),
          const SizedBox(height: 8),
          OutlinedButton.icon(icon: const Icon(Icons.copy), label: const Text('Copy words'), onPressed: () => copyToClipboard(context, phrase, what: 'Copied. Paste somewhere safe, then clear the clipboard.')),
          const SizedBox(height: 16),
          if (firstTime) FilledButton(onPressed: () => Navigator.of(context).popUntil((r) => r.isFirst), child: const Text('I have written them down')),
        ],
      ),
    );
  }
}

class RecoverWalletScreen extends StatefulWidget {
  const RecoverWalletScreen({super.key});
  @override
  State<RecoverWalletScreen> createState() => _RecoverWalletScreenState();
}

class _RecoverWalletScreenState extends State<RecoverWalletScreen> {
  final words = TextEditingController(), name = TextEditingController();
  final p1 = TextEditingController(), p2 = TextEditingController();
  final fileJson = TextEditingController(), filePass = TextEditingController();
  bool byFile = false;

  Future<void> recover() async {
    if (p1.text.length < 8) return toast(context, 'Use a passphrase of at least 8 characters for this phone');
    if (p1.text != p2.text) return toast(context, 'The passphrases do not match');
    final s = SessionScope.of(context);
    try {
      validatePhrase(words.text);
    } on FormatException catch (e) {
      return toast(context, e.message);
    }
    final ok = await runBusy<bool>(context, 'Rebuilding your wallet…', () async {
      await s.recoverWallet(words.text, name.text.trim(), p1.text);
      return true;
    });
    if (ok != null && mounted) Navigator.of(context).popUntil((r) => r.isFirst);
  }

  Future<void> importFile() async {
    if (filePass.text.isEmpty) return toast(context, 'Enter the wallet passphrase');
    final s = SessionScope.of(context);
    final ok = await runBusy<bool>(context, 'Opening the wallet…', () async {
      await s.importWallet(fileJson.text.trim(), filePass.text);
      return true;
    });
    if (ok != null && mounted) Navigator.of(context).popUntil((r) => r.isFirst);
  }

  @override
  Widget build(BuildContext context) => Scaffold(
        appBar: AppBar(title: const Text('Recover a wallet')),
        body: ListView(
          padding: const EdgeInsets.all(20),
          children: [
            SegmentedButton<bool>(
              segments: const [ButtonSegment(value: false, label: Text('Twelve words')), ButtonSegment(value: true, label: Text('Wallet file'))],
              selected: {byFile},
              onSelectionChanged: (v) => setState(() => byFile = v.first),
            ),
            const SizedBox(height: 16),
            if (!byFile) ...[
              const Text('Type the twelve words of your recovery phrase, in order. The same wallet, address and letters come back on this phone.', style: TextStyle(height: 1.4)),
              const SizedBox(height: 14),
              TextField(controller: words, minLines: 3, maxLines: 4, autocorrect: false, enableSuggestions: false, decoration: const InputDecoration(labelText: 'Recovery phrase')),
              const SizedBox(height: 12),
              TextField(controller: name, decoration: const InputDecoration(labelText: 'A name for this wallet (optional)')),
              const SizedBox(height: 12),
              PassphraseField(controller: p1, label: 'New passphrase for this phone'),
              const SizedBox(height: 12),
              PassphraseField(controller: p2, label: 'Passphrase again', onSubmitted: (_) => recover()),
              const SizedBox(height: 20),
              FilledButton(onPressed: recover, child: const Text('Recover wallet')),
              const SizedBox(height: 12),
              const Text('A wallet made before recovery phrases existed has no words. Use the wallet file instead: export it from Settings on the old phone, or copy keys\\savings.json from the PC.', style: TextStyle(color: Color(0xFF6F7883), fontSize: 13, height: 1.4)),
            ] else ...[
              const Text('Paste the contents of a sealed wallet file exported from another phone or made on a PC, and enter its passphrase.', style: TextStyle(height: 1.4)),
              const SizedBox(height: 14),
              TextField(controller: fileJson, maxLines: 6, decoration: const InputDecoration(labelText: 'Wallet file contents'), style: const TextStyle(fontFamily: 'monospace', fontSize: 12)),
              const SizedBox(height: 12),
              PassphraseField(controller: filePass, label: 'Its passphrase', onSubmitted: (_) => importFile()),
              const SizedBox(height: 20),
              FilledButton(onPressed: importFile, child: const Text('Import')),
            ],
          ],
        ),
      );
}
