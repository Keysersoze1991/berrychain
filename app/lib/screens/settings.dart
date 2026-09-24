import 'package:flutter/material.dart';

import '../main.dart';
import '../session.dart';
import 'common.dart';

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
          const Text('WALLET', style: TextStyle(fontSize: 11.5, letterSpacing: 1.2, fontWeight: FontWeight.w600, color: Color(0xFF6F7883))),
          const SizedBox(height: 6),
          const Text('Export copies the sealed wallet file to the clipboard. Paste it into a text file on a PC and it opens there with the same passphrase. Keep a copy somewhere safe; without the file and the passphrase the coins are gone.', style: TextStyle(height: 1.4)),
          const SizedBox(height: 10),
          OutlinedButton.icon(
            icon: const Icon(Icons.copy),
            label: const Text('Export sealed wallet file'),
            onPressed: () async {
              final json = await s.exportWalletJson();
              if (context.mounted) copyToClipboard(context, json, what: 'Sealed wallet copied. Paste it somewhere safe.');
            },
          ),
          const Divider(height: 32),
          const Text('BerryChain wallet 0.1. Verified light client: pinned genesis and checkpoint, proof-of-work checked on every header. Pre-audit software; do not hold value you cannot afford to lose.', style: TextStyle(color: Color(0xFF6F7883), fontSize: 13, height: 1.4)),
          const SizedBox(height: 6),
          const Text('berrychain.link', style: TextStyle(color: Palette.brass)),
        ],
      ),
    );
  }
}
