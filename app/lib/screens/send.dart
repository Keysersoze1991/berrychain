import 'package:flutter/material.dart';

import '../core/units.dart';
import '../main.dart';
import 'common.dart';

class SendScreen extends StatefulWidget {
  const SendScreen({super.key});
  @override
  State<SendScreen> createState() => _SendScreenState();
}

class _SendScreenState extends State<SendScreen> {
  final to = TextEditingController(), amount = TextEditingController(), memo = TextEditingController();

  Future<void> send() async {
    final int seeds;
    try {
      seeds = parseBerry(amount.text);
    } on FormatException catch (e) {
      return toast(context, e.message);
    }
    if (seeds <= 0) return toast(context, 'Enter an amount');
    final s = SessionScope.of(context);
    final ok = await showDialog<bool>(
      context: context,
      builder: (_) => AlertDialog(
        title: const Text('Send?'),
        content: Text('${formatBerry(seeds)} BERRY to\n${to.text.trim()}\n\nFee ${formatBerry(minFee)} BERRY to the miner. Sends are final once confirmed.'),
        actions: [
          TextButton(onPressed: () => Navigator.pop(context, false), child: const Text('Cancel')),
          FilledButton(onPressed: () => Navigator.pop(context, true), child: const Text('Send')),
        ],
      ),
    );
    if (ok != true || !mounted) return;
    final id = await runBusy(context, 'Signing and sending…', () => s.send(to.text.trim(), seeds, memo.text.trim()));
    if (id != null && mounted) {
      toast(context, 'Sent. It confirms in the next block.');
      s.refresh();
      Navigator.pop(context);
    }
  }

  @override
  Widget build(BuildContext context) {
    final s = SessionScope.of(context);
    return Scaffold(
      appBar: AppBar(title: const Text('Send BERRY')),
      body: ListView(
        padding: const EdgeInsets.all(20),
        children: [
          Text('Available: ${s.balance == null ? '–' : formatBerry(s.balance!)} BERRY', style: const TextStyle(color: Color(0xFF6F7883))),
          const SizedBox(height: 14),
          TextField(controller: to, decoration: const InputDecoration(labelText: 'To (brry1…)'), autocorrect: false, style: const TextStyle(fontFamily: 'monospace', fontSize: 13)),
          const SizedBox(height: 12),
          TextField(controller: amount, keyboardType: const TextInputType.numberWithOptions(decimal: true), decoration: const InputDecoration(labelText: 'Amount in BERRY', hintText: '0.25')),
          const SizedBox(height: 12),
          TextField(controller: memo, maxLength: 200, decoration: const InputDecoration(labelText: 'Memo (public, optional)')),
          const SizedBox(height: 8),
          FilledButton(onPressed: send, child: const Text('Review and send')),
          const SizedBox(height: 12),
          const Text('A memo is visible to everyone on the ledger. For anything private, send a letter instead.', style: TextStyle(color: Color(0xFF6F7883), fontSize: 13)),
        ],
      ),
    );
  }
}
