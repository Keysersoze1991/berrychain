import 'package:flutter/material.dart';

import '../core/letters.dart';
import '../core/units.dart';
import '../main.dart';
import '../session.dart';
import 'common.dart';

class LettersScreen extends StatelessWidget {
  const LettersScreen({super.key});

  @override
  Widget build(BuildContext context) {
    final s = SessionScope.of(context);
    return DefaultTabController(
      length: 2,
      child: Scaffold(
        appBar: AppBar(
          title: const Text('Letters'),
          bottom: const TabBar(indicatorColor: Palette.gold, labelColor: Colors.white, unselectedLabelColor: Color(0xFFA9BACC), tabs: [Tab(text: 'Inbox'), Tab(text: 'Sent')]),
        ),
        floatingActionButton: FloatingActionButton.extended(
          backgroundColor: Palette.gold,
          foregroundColor: Palette.sea,
          icon: const Icon(Icons.edit),
          label: const Text('Write'),
          onPressed: () => Navigator.push(context, MaterialPageRoute(builder: (_) => const ComposeScreen())),
        ),
        body: ListenableBuilder(
          listenable: s,
          builder: (context, _) => TabBarView(children: [
            _LetterList(items: s.inbox, incoming: true),
            _LetterList(items: s.sent, incoming: false),
          ]),
        ),
      ),
    );
  }
}

class _LetterList extends StatelessWidget {
  final List<LetterItem> items;
  final bool incoming;
  const _LetterList({required this.items, required this.incoming});

  @override
  Widget build(BuildContext context) {
    final s = SessionScope.of(context);
    return RefreshIndicator(
      onRefresh: s.refresh,
      child: items.isEmpty
          ? ListView(children: const [Padding(padding: EdgeInsets.all(32), child: Text('Nothing here yet. Pull down to check again.', textAlign: TextAlign.center, style: TextStyle(color: Color(0xFF6F7883))))])
          : ListView.builder(
              itemCount: items.length,
              itemBuilder: (context, i) {
                final l = items[i];
                final other = incoming ? l.from : l.to;
                return ListTile(
                  leading: Icon(incoming ? Icons.mail_outline : Icons.send_outlined, color: Palette.brass),
                  title: Text(shortAddress(other), style: const TextStyle(fontFamily: 'monospace')),
                  subtitle: Text('block ${l.height} · ${l.size} bytes${l.amount > 0 ? ' · +${formatBerry(l.amount)} BERRY${l.verified ? ' ✓' : ''}' : ''}'),
                  trailing: const Icon(Icons.chevron_right),
                  onTap: () => Navigator.push(context, MaterialPageRoute(builder: (_) => ReadLetterScreen(l, incoming: incoming))),
                );
              },
            ),
    );
  }
}

class ReadLetterScreen extends StatefulWidget {
  final LetterItem letter;
  final bool incoming;
  const ReadLetterScreen(this.letter, {super.key, required this.incoming});
  @override
  State<ReadLetterScreen> createState() => _ReadLetterScreenState();
}

class _ReadLetterScreenState extends State<ReadLetterScreen> {
  OpenedLetter? opened;
  String? error;

  @override
  void initState() {
    super.initState();
    SessionScope.of(context).readLetter(widget.letter).then((o) => setState(() => opened = o)).catchError((e) => setState(() => error = '$e'));
  }

  @override
  Widget build(BuildContext context) {
    final l = widget.letter;
    final o = opened;
    return Scaffold(
      appBar: AppBar(title: Text(o?.subject.isNotEmpty == true ? o!.subject : 'Letter')),
      body: ListView(
        padding: const EdgeInsets.all(20),
        children: [
          Text('${widget.incoming ? 'From' : 'To'}: ${widget.incoming ? l.from : l.to}${o?.fromName.isNotEmpty == true ? '  (${o!.fromName})' : ''}', style: const TextStyle(fontFamily: 'monospace', fontSize: 12)),
          Text('Block ${l.height}${l.amount > 0 ? ' · ${formatBerry(l.amount)} BERRY attached${l.verified ? ', verified against the chain' : ''}' : ''}', style: const TextStyle(color: Color(0xFF6F7883), fontSize: 13)),
          if (o?.replyTo != null) Text('Reply to letter ${shortAddress(o!.replyTo!)}', style: const TextStyle(color: Color(0xFF6F7883), fontSize: 13)),
          const Divider(height: 28),
          if (error != null) Text(error!, style: const TextStyle(color: Palette.band)),
          if (o == null && error == null) const Center(child: Padding(padding: EdgeInsets.all(20), child: CircularProgressIndicator())),
          if (o != null) SelectableText(o.body, style: TextStyle(fontSize: 16, height: 1.5, fontFamily: o.isHex ? 'monospace' : null)),
          if (o != null && widget.incoming) ...[
            const SizedBox(height: 24),
            OutlinedButton.icon(
              icon: const Icon(Icons.reply),
              label: const Text('Reply'),
              onPressed: () => Navigator.push(context, MaterialPageRoute(builder: (_) => ComposeScreen(to: l.from, subject: o.subject.startsWith('Re:') ? o.subject : 'Re: ${o.subject}', replyTo: l.id))),
            ),
          ],
        ],
      ),
    );
  }
}

class ComposeScreen extends StatefulWidget {
  final String? to, subject, replyTo;
  const ComposeScreen({super.key, this.to, this.subject, this.replyTo});
  @override
  State<ComposeScreen> createState() => _ComposeScreenState();
}

class _ComposeScreenState extends State<ComposeScreen> {
  late final to = TextEditingController(text: widget.to ?? '');
  late final subject = TextEditingController(text: widget.subject ?? '');
  final body = TextEditingController(), amount = TextEditingController();

  Future<void> send() async {
    if (body.text.trim().isEmpty) return toast(context, 'Write something first');
    int seeds = 0;
    if (amount.text.trim().isNotEmpty) {
      try {
        seeds = parseBerry(amount.text);
      } on FormatException catch (e) {
        return toast(context, e.message);
      }
    }
    final s = SessionScope.of(context);
    final id = await runBusy(context, 'Sealing and sending…', () => s.sendLetter(to.text.trim(), subject.text.trim(), body.text, seeds, replyTo: widget.replyTo));
    if (id != null && mounted) {
      toast(context, 'Sealed and sent. Readable once the block is mined.');
      s.refresh();
      Navigator.pop(context);
    }
  }

  @override
  Widget build(BuildContext context) {
    final s = SessionScope.of(context);
    return Scaffold(
      appBar: AppBar(title: const Text('Write a letter')),
      body: ListView(
        padding: const EdgeInsets.all(20),
        children: [
          TextField(controller: to, decoration: const InputDecoration(labelText: 'To (brry1…)'), autocorrect: false, style: const TextStyle(fontFamily: 'monospace', fontSize: 13)),
          const SizedBox(height: 12),
          TextField(controller: subject, decoration: const InputDecoration(labelText: 'Subject (sealed)')),
          const SizedBox(height: 12),
          TextField(controller: body, minLines: 6, maxLines: 14, decoration: const InputDecoration(labelText: 'Letter (sealed)')),
          const SizedBox(height: 12),
          TextField(controller: amount, keyboardType: const TextInputType.numberWithOptions(decimal: true), decoration: const InputDecoration(labelText: 'BERRY to send with it (optional)')),
          const SizedBox(height: 16),
          FilledButton.icon(icon: const Icon(Icons.lock_outline), label: const Text('Seal and send'), onPressed: send),
          const SizedBox(height: 12),
          Text('Fee ${formatBerry(s.letterFee ?? minFee)} BERRY. Only the recipient can read this; the ledger shows the two addresses, the time and the size.', style: const TextStyle(color: Color(0xFF6F7883), fontSize: 13)),
        ],
      ),
    );
  }
}
