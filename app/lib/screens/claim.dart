import 'package:flutter/material.dart';

import '../core/units.dart';
import '../main.dart';
import 'common.dart';

class ClaimScreen extends StatefulWidget {
  const ClaimScreen({super.key});
  @override
  State<ClaimScreen> createState() => _ClaimScreenState();
}

class _ClaimScreenState extends State<ClaimScreen> {
  final name = TextEditingController();

  Future<void> claim() async {
    if (name.text.trim().isEmpty) return toast(context, 'Pick a name');
    final s = SessionScope.of(context);
    final amount = await runBusy(context, 'Working for your starter. The phone hashes for a little while to prove you are one person, not a thousand. Keep the app open.', () => s.claimStarter(name.text.trim()));
    if (amount != null && mounted) {
      await showDialog<void>(
        context: context,
        builder: (_) => AlertDialog(
          title: const Text('Claimed'),
          content: Text('${formatBerry(amount)} BERRY is on its way. It lands once the block is mined, usually within a minute. Pull down on the home screen to refresh.'),
          actions: [TextButton(onPressed: () => Navigator.pop(context), child: const Text('OK'))],
        ),
      );
      if (mounted) Navigator.pop(context);
    }
  }

  @override
  Widget build(BuildContext context) {
    final s = SessionScope.of(context);
    return Scaffold(
      appBar: AppBar(title: const Text('Claim your starter')),
      body: ListView(
        padding: const EdgeInsets.all(20),
        children: [
          Text('Every new account gets ${s.starterAmount == null ? 'a starter grant' : '${formatBerry(s.starterAmount!)} BERRY'} from the treasury, and claims it itself. The claim also publishes your name and receiving key on the chain, which is what lets people send you letters. Once per wallet.', style: const TextStyle(height: 1.4)),
          const SizedBox(height: 10),
          const Text('The starter halves every 10,000 claims, so the earlier you claim, the more you get. The name is public; the phone does a few seconds of work before the chain accepts the claim.', style: TextStyle(color: Color(0xFF6F7883), height: 1.4)),
          const SizedBox(height: 18),
          TextField(controller: name, decoration: const InputDecoration(labelText: 'Your name on the chain'), onSubmitted: (_) => claim()),
          const SizedBox(height: 20),
          FilledButton(style: FilledButton.styleFrom(backgroundColor: Palette.gold, foregroundColor: Palette.sea), onPressed: claim, child: const Text('Claim my starter')),
        ],
      ),
    );
  }
}
