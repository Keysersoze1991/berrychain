import 'dart:async';
import 'dart:convert';

import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:image_picker/image_picker.dart';

import '../core/letters.dart';
import '../core/parcels.dart';
import '../core/photo.dart';
import '../core/save.dart';
import 'package:file_picker/file_picker.dart';
import '../core/crypto.dart';
import '../core/units.dart';
import '../main.dart';
import '../session.dart';
import 'common.dart';
import 'contacts.dart';

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
          bottom: TabBar(
            indicatorColor: Palette.gold,
            labelColor: Colors.white,
            unselectedLabelColor: const Color(0xFFA9BACC),
            tabs: [
              ListenableBuilder(listenable: s, builder: (_, __) => Tab(text: s.unreadCount == 0 ? 'Letters' : 'Letters (${s.unreadCount} unread)')),
              ListenableBuilder(listenable: s, builder: (_, __) => Tab(text: s.drafts.isEmpty ? 'Drafts' : 'Drafts (${s.drafts.length})')),
            ],
          ),
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
          builder: (context, _) => const TabBarView(children: [_FolderList(), _DraftList()]),
        ),
      ),
    );
  }
}

String whenText(DateTime? t) {
  if (t == null) return '';
  final l = t.toLocal();
  const months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  final now = DateTime.now();
  final sameDay = l.year == now.year && l.month == now.month && l.day == now.day;
  final hm = '${l.hour.toString().padLeft(2, '0')}:${l.minute.toString().padLeft(2, '0')}';
  if (sameDay) return 'today $hm';
  return '${l.day} ${months[l.month - 1]}${l.year == now.year ? '' : ' ${l.year}'} $hm';
}

/// A row per friend or crew, newest correspondence first.
class _FolderList extends StatelessWidget {
  const _FolderList();

  @override
  Widget build(BuildContext context) {
    final s = SessionScope.of(context);
    final folders = s.folders;
    return RefreshIndicator(
      onRefresh: s.refresh,
      child: folders.isEmpty
          ? ListView(children: const [Padding(padding: EdgeInsets.all(32), child: Text('Nothing here yet. Write to someone, or pull down to check again.', textAlign: TextAlign.center, style: TextStyle(color: Color(0xFF6F7883))))])
          : ListView.builder(
              itemCount: folders.length,
              itemBuilder: (context, i) {
                final f = folders[i];
                final latest = f.letters.first;
                final isHm = f.address == Network.harbourmaster;
                return ListTile(
                  leading: CircleAvatar(
                    backgroundColor: f.crew != null ? const Color(0xFFDCCFB4) : (isHm ? Palette.gold : const Color(0xFFDCCFB4)),
                    foregroundColor: Palette.sea,
                    child: Icon(f.crew != null ? Icons.groups_outlined : (isHm ? Icons.anchor : Icons.folder_outlined), size: 20),
                  ),
                  title: Text(f.title, style: TextStyle(fontWeight: f.unread > 0 ? FontWeight.w700 : FontWeight.w500)),
                  subtitle: Text('${f.letters.length} letter${f.letters.length == 1 ? '' : 's'}${f.unread > 0 ? ' · ${f.unread} unread' : ''} · latest ${whenText(s.cachedLetterTime(latest)).isEmpty ? 'block ${latest.height}' : whenText(s.cachedLetterTime(latest))}'),
                  trailing: f.unread > 0
                      ? Container(padding: const EdgeInsets.symmetric(horizontal: 9, vertical: 3), decoration: BoxDecoration(color: Palette.band, borderRadius: BorderRadius.circular(12)), child: Text('${f.unread}', style: const TextStyle(color: Colors.white, fontWeight: FontWeight.w700, fontSize: 12)))
                      : const Icon(Icons.chevron_right),
                  onTap: () => Navigator.push(context, MaterialPageRoute(builder: (_) => ConversationScreen(f.key))),
                );
              },
            ),
    );
  }
}

/// Everything with one friend or crew, in order, with Write at the bottom.
class ConversationScreen extends StatefulWidget {
  final String folderKey;
  const ConversationScreen(this.folderKey, {super.key});
  @override
  State<ConversationScreen> createState() => _ConversationScreenState();
}

class _ConversationScreenState extends State<ConversationScreen> {
  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) => _loadTimes());
  }

  Future<void> _loadTimes() async {
    final s = SessionScope.of(context);
    final f = s.folders.where((f) => f.key == widget.folderKey).firstOrNull;
    if (f == null) return;
    for (final l in f.letters.take(40)) {
      if (s.cachedLetterTime(l) == null) await s.letterTime(l);
    }
    if (mounted) setState(() {});
  }

  @override
  Widget build(BuildContext context) {
    final s = SessionScope.of(context);
    return ListenableBuilder(
      listenable: s,
      builder: (context, _) {
        final f = s.folders.where((f) => f.key == widget.folderKey).firstOrNull;
        if (f == null) return Scaffold(appBar: AppBar(title: const Text('Letters')), body: const Center(child: Text('Nothing here any more.')));
        final me = s.wallet!.address;
        return Scaffold(
          appBar: AppBar(title: Text(f.title)),
          floatingActionButton: FloatingActionButton.extended(
            backgroundColor: Palette.gold,
            foregroundColor: Palette.sea,
            icon: const Icon(Icons.edit),
            label: Text(f.crew != null ? 'Write to the crew' : 'Write'),
            onPressed: () => Navigator.push(context, MaterialPageRoute(builder: (_) => f.crew != null ? ComposeScreen(group: f.crew) : ComposeScreen(to: f.address))),
          ),
          body: RefreshIndicator(
            onRefresh: s.refresh,
            child: ListView.builder(
              padding: const EdgeInsets.only(bottom: 90),
              itemCount: f.letters.length,
              itemBuilder: (context, i) {
                final l = f.letters[i];
                final incoming = l.from != me;
                final unread = s.isUnread(l);
                final when = whenText(s.cachedLetterTime(l));
                final removed = s.isRemoved(l.id);
                return ListTile(
                  leading: Icon(incoming ? Icons.mail_outline : Icons.send_outlined, color: removed ? const Color(0xFF9A8D94) : (unread ? Palette.band : Palette.brass)),
                  title: Text(incoming ? (f.crew != null ? 'From ${s.contacts.where((c) => c.address == l.from).map((c) => c.label).firstOrNull ?? shortAddress(l.from)}' : 'Received') : (f.crew != null ? 'To ${s.contacts.where((c) => c.address == l.to).map((c) => c.label).firstOrNull ?? shortAddress(l.to)}' : 'Sent'),
                      style: TextStyle(fontWeight: unread ? FontWeight.w700 : FontWeight.w500, color: removed ? const Color(0xFF9A8D94) : null)),
                  subtitle: Text('${removed ? 'removed · ' : ''}${when.isEmpty ? 'block ${l.height}' : when}${l.amount > 0 ? ' · +${formatBerry(l.amount)} BERRY${l.verified ? ' ✓' : ''}' : ''}'),
                  trailing: unread ? const Icon(Icons.circle, size: 10, color: Palette.band) : const Icon(Icons.chevron_right),
                  onTap: () => Navigator.push(context, MaterialPageRoute(builder: (_) => ReadLetterScreen(l, incoming: incoming))),
                  onLongPress: () => removed ? s.restoreLetter(l.id) : confirmRemove(context, l),
                );
              },
            ),
          ),
        );
      },
    );
  }
}

/// Removes or burns a letter after saying plainly what each means. Returns
/// true if the letter is no longer shown.
Future<bool> confirmRemove(BuildContext context, LetterItem l) async {
  final s = SessionScope.of(context);
  final w = s.wallet!;
  final mine = l.from == w.address;
  // A received letter can only be made unreadable everywhere if its key lives on this phone alone.
  final pub = l.encPub;
  final burnableKey = pub != null && pub != w.encRootPub && w.keyFor(pub) != null && !s.keyIsBackedUp(pub);
  final choice = await showModalBottomSheet<String>(
    context: context,
    showDragHandle: true,
    builder: (ctx) => ListView(
      shrinkWrap: true,
      padding: const EdgeInsets.fromLTRB(20, 0, 20, 24),
      children: [
        const Text('Remove this letter', style: TextStyle(fontWeight: FontWeight.w600, fontSize: 17)),
        const SizedBox(height: 6),
        const Text('The sealed copy stays on the chain either way, as every letter does; only a key that opens it could ever read it.', style: TextStyle(color: Color(0xFF6F7883), fontSize: 13, height: 1.4)),
        const SizedBox(height: 14),
        ListTile(
          contentPadding: EdgeInsets.zero,
          leading: const Icon(Icons.delete_outline, color: Palette.brass),
          title: const Text('Remove from this phone'),
          subtitle: const Text('Hidden here. You can show it again from Settings.'),
          onTap: () => Navigator.pop(ctx, 'remove'),
        ),
        ListTile(
          contentPadding: EdgeInsets.zero,
          leading: const Icon(Icons.local_fire_department_outlined, color: Palette.band),
          title: const Text('Burn'),
          subtitle: Text(mine
              ? 'Gone from this phone for good, and your key to this letter is destroyed with it: nothing on your side, not even your twelve words, can open the chain copy again. The recipient keeps theirs unless they burn it too.'
              : (burnableKey
                  ? 'Gone from this phone for good. To make it unreadable everywhere, burn the key it was sealed to in Settings; that covers every letter sealed to that key.'
                  : 'Gone from this phone for good, not restorable from Settings. Your twelve words could still rebuild the key it was sealed to. For letters nobody can ever recover, rotate your key with no backup in Settings.')),
          onTap: () => Navigator.pop(ctx, 'burn'),
        ),
        const SizedBox(height: 6),
        TextButton(onPressed: () => Navigator.pop(ctx, null), child: const Text('Keep it')),
      ],
    ),
  );
  if (choice == 'remove') {
    await s.removeLetter(l.id);
    if (context.mounted) toast(context, 'Removed from this phone');
    return true;
  }
  if (choice == 'burn') {
    if (!context.mounted) return false;
    final sure = await showDialog<bool>(
      context: context,
      builder: (_) => AlertDialog(
        title: const Text('Burn this letter?'),
        content: Text(mine ? 'This cannot be undone. Your key to it is destroyed.' : 'This cannot be undone on this phone.'),
        actions: [
          TextButton(onPressed: () => Navigator.pop(context, false), child: const Text('Keep')),
          FilledButton(style: FilledButton.styleFrom(backgroundColor: Palette.band, foregroundColor: Colors.white), onPressed: () => Navigator.pop(context, true), child: const Text('Burn')),
        ],
      ),
    );
    if (sure == true) {
      await s.burnLetter(l);
      if (context.mounted) toast(context, mine ? 'Burned. Your key to it is gone.' : 'Burned on this phone.');
      return true;
    }
  }
  return false;
}

class _DraftList extends StatelessWidget {
  const _DraftList();

  @override
  Widget build(BuildContext context) {
    final s = SessionScope.of(context);
    final drafts = s.drafts;
    if (drafts.isEmpty) {
      return ListView(children: const [Padding(padding: EdgeInsets.all(32), child: Text('No drafts. A letter you start and leave is kept here until you send or discard it.', textAlign: TextAlign.center, style: TextStyle(color: Color(0xFF6F7883))))]);
    }
    return ListView.builder(
      itemCount: drafts.length,
      itemBuilder: (context, i) {
        final d = drafts[i];
        final g = s.groupById(d.groupId);
        final who = g != null ? 'To the crew ${g.name}' : d.to.isEmpty ? 'No address yet' : 'To ${shortAddress(d.to)}';
        final when = DateTime.fromMillisecondsSinceEpoch(d.updated);
        return Dismissible(
          key: ValueKey(d.id),
          direction: DismissDirection.endToStart,
          background: Container(color: Palette.band, alignment: Alignment.centerRight, padding: const EdgeInsets.only(right: 20), child: const Icon(Icons.delete_outline, color: Colors.white)),
          onDismissed: (_) => s.deleteDraft(d.id),
          child: ListTile(
            leading: const Icon(Icons.drafts_outlined, color: Palette.brass),
            title: Text(d.subject.isNotEmpty ? d.subject : (d.body.trim().isNotEmpty ? d.body.trim().split('\n').first : 'Untitled draft'), maxLines: 1, overflow: TextOverflow.ellipsis),
            subtitle: Text('$who · ${when.day}/${when.month} ${when.hour.toString().padLeft(2, '0')}:${when.minute.toString().padLeft(2, '0')}${d.photoB64 != null ? ' · picture' : ''}'),
            trailing: const Icon(Icons.chevron_right),
            onTap: () => Navigator.push(context, MaterialPageRoute(builder: (_) => ComposeScreen(draft: d))),
          ),
        );
      },
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
  DateTime? when;

  @override
  void initState() {
    super.initState();
    final s = SessionScope.of(context);
    s.letterTime(widget.letter).then((t) {
      if (mounted) setState(() => when = t);
    });
    s.readLetter(widget.letter).then((o) async {
      if (!mounted) return;
      setState(() => opened = o);
      await s.markRead(widget.letter);
      final g = o.group;
      if (g != null) {
        await s.noteCrew(widget.letter.id, g.id);
        if (widget.incoming) {
          final added = await s.adoptGroup(g, widget.letter.from);
          if (added && mounted) toast(context, 'Crew "${g.name}" saved to Contacts so you can reply to everyone');
        }
      }
    }).catchError((e) {
      if (mounted) setState(() => error = '$e');
    });
  }

  @override
  Widget build(BuildContext context) {
    final s = SessionScope.of(context);
    final l = widget.letter;
    final o = opened;
    final group = o?.group == null ? null : (s.groupById(o!.group!.id) ?? o.group);
    return Scaffold(
      appBar: AppBar(
        title: Text(o?.subject.isNotEmpty == true ? o!.subject : 'Letter'),
        actions: [
          IconButton(
            icon: Icon(s.isRemoved(l.id) ? Icons.restore_from_trash_outlined : Icons.delete_outline),
            tooltip: s.isRemoved(l.id) ? 'Put back' : 'Remove from this phone',
            onPressed: () async {
              if (s.isRemoved(l.id)) {
                await s.restoreLetter(l.id);
              } else {
                final gone = await confirmRemove(context, l);
                if (context.mounted && gone) Navigator.pop(context);
              }
            },
          ),
        ],
      ),
      body: ListView(
        padding: const EdgeInsets.all(20),
        children: [
          Text('${widget.incoming ? 'From' : 'To'}: ${widget.incoming ? l.from : l.to}${o?.fromName.isNotEmpty == true ? '  (${o!.fromName})' : ''}', style: const TextStyle(fontFamily: 'monospace', fontSize: 12)),
          if (group != null)
            Padding(
              padding: const EdgeInsets.only(top: 4),
              child: Text('Sent to the crew "${group.name}" (${group.members.length + 1} people, including you)', style: const TextStyle(color: Palette.brass, fontSize: 13, fontWeight: FontWeight.w600)),
            ),
          Text('${widget.incoming ? 'Received' : 'Sent'} ${when == null ? 'in block ${l.height}' : '${whenText(when)} (block ${l.height})'}${l.amount > 0 ? ' · ${formatBerry(l.amount)} BERRY attached${l.verified ? ', verified against the chain' : ''}' : ''}', style: const TextStyle(color: Color(0xFF6F7883), fontSize: 13)),
          if (o?.replyTo != null) Text('Reply to letter ${shortAddress(o!.replyTo!)}', style: const TextStyle(color: Color(0xFF6F7883), fontSize: 13)),
          const Divider(height: 28),
          if (error != null) Text(error!, style: const TextStyle(color: Palette.band)),
          if (o == null && error == null) const Center(child: Padding(padding: EdgeInsets.all(20), child: CircularProgressIndicator())),
          if (o?.photoJpeg != null) ...[
            ClipRRect(borderRadius: BorderRadius.circular(10), child: Image.memory(o!.photoJpeg!, fit: BoxFit.contain)),
            const SizedBox(height: 16),
          ],
          if (o?.parcel != null) ...[
            _ParcelCard(o!.parcel!),
            const SizedBox(height: 16),
          ],
          if (o != null) SelectableText(o.body, style: TextStyle(fontSize: 16, height: 1.5, fontFamily: o.isHex ? 'monospace' : null)),
          if (o != null && widget.incoming) ...[
            const SizedBox(height: 24),
            OutlinedButton.icon(
              icon: const Icon(Icons.reply),
              label: Text(group != null ? 'Reply to ${o.fromName.isNotEmpty ? o.fromName : 'the sender'} only' : 'Reply'),
              onPressed: () => Navigator.push(context, MaterialPageRoute(builder: (_) => ComposeScreen(to: l.from, subject: o.subject.startsWith('Re:') ? o.subject : 'Re: ${o.subject}', replyTo: l.id))),
            ),
            if (group != null) ...[
              const SizedBox(height: 10),
              FilledButton.icon(
                icon: const Icon(Icons.reply_all),
                label: Text('Reply to the crew (${group.members.length} people)'),
                onPressed: () => Navigator.push(context, MaterialPageRoute(builder: (_) => ComposeScreen(group: s.groupById(group.id) ?? group, subject: o.subject.startsWith('Re:') ? o.subject : 'Re: ${o.subject}', replyTo: l.id))),
              ),
            ],
          ],
        ],
      ),
    );
  }
}

class ComposeScreen extends StatefulWidget {
  final String? to, subject, replyTo;
  final LetterGroup? group;
  final Draft? draft;
  const ComposeScreen({super.key, this.to, this.subject, this.replyTo, this.group, this.draft});
  @override
  State<ComposeScreen> createState() => _ComposeScreenState();
}

class _ComposeScreenState extends State<ComposeScreen> {
  late final TextEditingController to, subject, body;
  final amount = TextEditingController();
  late final String draftId;
  String? replyTo;
  LetterGroup? group;
  Uint8List? photo;
  Uint8List? parcelBytes;
  String? parcelName;
  ParcelTerms? terms;
  String? toName;
  bool toValid = false, sent = false;
  Timer? _autosave;

  @override
  void initState() {
    super.initState();
    final s = SessionScope.of(context);
    final d = widget.draft;
    draftId = d?.id ?? '${DateTime.now().millisecondsSinceEpoch}-${identityHashCode(this)}';
    to = TextEditingController(text: d?.to ?? widget.to ?? '');
    subject = TextEditingController(text: d?.subject ?? widget.subject ?? '');
    body = TextEditingController(text: d?.body ?? '');
    replyTo = d?.replyTo ?? widget.replyTo;
    group = widget.group ?? s.groupById(d?.groupId);
    if (d?.photoB64 != null) {
      try {
        photo = base64Decode(d!.photoB64!);
      } catch (_) {}
    }
    for (final c in [to, subject, body]) {
      c.addListener(_changed);
    }
    to.addListener(() => lookup(to.text.trim()));
    if (to.text.isNotEmpty) lookup(to.text.trim());
  }

  @override
  void dispose() {
    _autosave?.cancel();
    if (!sent) _saveNow();
    super.dispose();
  }

  void _changed() {
    setState(() {});
    _autosave?.cancel();
    _autosave = Timer(const Duration(seconds: 2), _saveNow);
  }

  Future<void> _saveNow() async {
    if (sent) return;
    final s = SessionScope.of(context);
    await s.saveDraft(Draft(draftId,
        to: group == null ? to.text.trim() : '', subject: subject.text, body: body.text, replyTo: replyTo, groupId: group?.id, photoB64: photo == null ? null : base64Encode(photo!)));
  }

  Future<void> lookup(String addr) async {
    final valid = isValidAddress(addr);
    if (mounted) {
      setState(() {
        toValid = valid;
        toName = null;
      });
    }
    if (!valid) return;
    final n = await SessionScope.of(context).lookupName(addr);
    if (mounted && to.text.trim() == addr) setState(() => toName = n);
  }

  Future<void> takePhoto(ImageSource source) async {
    final picked = await ImagePicker().pickImage(source: source, maxWidth: 1200, maxHeight: 1200, imageQuality: 85);
    if (picked == null || !mounted) return;
    final raw = await picked.readAsBytes();
    if (!mounted) return;
    final small = await runBusy<Uint8List>(context, 'Shrinking the picture to fit the envelope…', () => compute(shrinkPhotoInIsolate, shrinkPhotoArgs(raw, 400, 18 * 1024)));
    if (small != null) {
      setState(() => photo = small);
      _changed();
    }
  }

  Future<void> discard() async {
    final s = SessionScope.of(context);
    sent = true; // do not re-save on dispose
    await s.deleteDraft(draftId);
    if (mounted) Navigator.pop(context);
  }

  Future<void> pickParcel() async {
    final s = SessionScope.of(context);
    try {
      terms ??= await s.parcelTermsNow();
    } catch (e) {
      if (!mounted) return;
      return toast(context, 'The parcel room is not answering: ${'$e'.replaceFirst(RegExp(r'^\w+Error: '), '')}');
    }
    final picked = await FilePicker.pickFiles();
    final f = picked.firstOrNull;
    if (f == null) return;
    final n = (await f.length()) ?? 0;
    if (!mounted) return;
    if (n + 64 > terms!.maxBytes) return toast(context, 'That file is ${formatBytes(n)}; a parcel can be at most ${formatBytes(terms!.maxBytes)}');
    final bytes = await f.readAsBytes();
    if (!mounted) return;
    setState(() {
      parcelBytes = bytes;
      parcelName = f.name;
    });
  }

  Future<void> send() async {
    if (body.text.trim().isEmpty && photo == null && parcelBytes == null) return toast(context, 'Write something first');
    int seeds = 0;
    if (amount.text.trim().isNotEmpty) {
      try {
        seeds = parseBerry(amount.text);
      } on FormatException catch (e) {
        return toast(context, e.message);
      }
    }
    final s = SessionScope.of(context);
    final g = group;
    if (g != null) {
      final n = g.members.where((m) => m != s.wallet!.address).length;
      final fee = s.letterFee ?? minFee;
      final ok = await showDialog<bool>(
        context: context,
        builder: (_) => AlertDialog(
          title: Text('Send to ${g.name}?'),
          content: Text('One sealed copy to each of $n people. Fees ${formatBerry(n * fee)} BERRY${seeds > 0 ? ', plus ${formatBerry(seeds)} BERRY to each' : ''}.'),
          actions: [
            TextButton(onPressed: () => Navigator.pop(context, false), child: const Text('Cancel')),
            FilledButton(onPressed: () => Navigator.pop(context, true), child: const Text('Send')),
          ],
        ),
      );
      if (ok != true || !mounted) return;
    }
    final result = await runBusy(context, g == null ? 'Sealing and sending…' : 'Sealing ${g.members.length} copies and sending…', () async {
      ParcelRef? ref;
      if (parcelBytes != null) {
        ref = await s.sendParcel(parcelBytes!, parcelName ?? 'parcel', progress: (m) => s.claimProgress.value = m);
        s.claimProgress.value = '';
      }
      if (g != null) return s.sendGroupLetter(g, subject.text.trim(), body.text, seeds, replyTo: replyTo, photoJpeg: photo, parcel: ref);
      return s.sendLetter(to.text.trim(), subject.text.trim(), body.text, seeds, replyTo: replyTo, photoJpeg: photo, parcel: ref);
    }, progress: s.claimProgress);
    if (result != null && mounted) {
      sent = true;
      await s.deleteDraft(draftId);
      if (!mounted) return;
      toast(context, g == null ? 'Sealed and sent. Readable once the block is mined.' : 'Sealed and sent to the whole crew ${g.name}.');
      s.refresh();
      Navigator.pop(context);
    }
  }

  @override
  Widget build(BuildContext context) {
    final s = SessionScope.of(context);
    final g = group;
    final budget = textBudget(photoJpeg: photo, group: g);
    final used = composeLetter(body.text, subject: subject.text, replyTo: replyTo, senderName: s.wallet!.label, group: g).length - composeLetter('', group: g).length;
    final left = budget - used;
    final fee = s.letterFee ?? minFee;
    final copies = g == null ? 1 : g.members.where((m) => m != s.wallet!.address).length;
    return Scaffold(
      appBar: AppBar(
        title: Text(widget.draft != null ? 'Draft' : 'Write a letter'),
        actions: [
          IconButton(icon: const Icon(Icons.photo_camera_outlined), tooltip: 'Take a picture', onPressed: photo == null ? () => takePhoto(ImageSource.camera) : null),
          IconButton(icon: const Icon(Icons.photo_library_outlined), tooltip: 'Picture from gallery', onPressed: photo == null ? () => takePhoto(ImageSource.gallery) : null),
          IconButton(icon: const Icon(Icons.attach_file), tooltip: 'Attach a file (a parcel)', onPressed: parcelBytes == null ? pickParcel : null),
          IconButton(icon: const Icon(Icons.delete_outline), tooltip: 'Discard draft', onPressed: discard),
        ],
      ),
      body: ListView(
        padding: const EdgeInsets.all(20),
        children: [
          if (g != null)
            InputDecorator(
              decoration: InputDecoration(
                labelText: 'To crew',
                suffixIcon: IconButton(icon: const Icon(Icons.close), tooltip: 'Write to one person instead', onPressed: () => setState(() => group = null)),
              ),
              child: Wrap(
                spacing: 6,
                runSpacing: -6,
                children: [
                  Chip(avatar: const Icon(Icons.groups_outlined, size: 18), label: Text(g.name, style: const TextStyle(fontWeight: FontWeight.w600))),
                  for (final m in g.members.where((m) => m != s.wallet!.address))
                    Chip(label: Text(s.contacts.where((c) => c.address == m).map((c) => c.label).firstOrNull ?? shortAddress(m), style: const TextStyle(fontSize: 12.5))),
                ],
              ),
            )
          else ...[
            TextField(
              controller: to,
              decoration: InputDecoration(
                labelText: 'To (brry1…)',
                suffixIcon: IconButton(
                  icon: const Icon(Icons.people_outline),
                  tooltip: 'Choose from your people or crews',
                  onPressed: () async {
                    final picked = await pickRecipient(context);
                    if (picked is Contact) setState(() => to.text = picked.address);
                    if (picked is LetterGroup) {
                      setState(() {
                        group = picked;
                        to.text = '';
                      });
                      _changed();
                    }
                  },
                ),
              ),
              autocorrect: false,
              style: const TextStyle(fontFamily: 'monospace', fontSize: 13),
            ),
            if (to.text.trim().isNotEmpty)
              Padding(
                padding: const EdgeInsets.only(top: 6),
                child: Text(
                  !toValid ? 'Not a BerryChain address yet' : toName == null ? 'Looking up…' : toName!.isEmpty ? 'This address has no registered name; check it carefully' : 'Sending to $toName',
                  style: TextStyle(fontSize: 13, fontWeight: FontWeight.w600, color: !toValid ? Palette.band : (toName?.isNotEmpty == true ? Palette.leaf : const Color(0xFF6F7883))),
                ),
              ),
          ],
          const SizedBox(height: 12),
          TextField(controller: subject, decoration: const InputDecoration(labelText: 'Subject (sealed)')),
          const SizedBox(height: 12),
          TextField(controller: body, minLines: 6, maxLines: 14, decoration: const InputDecoration(labelText: 'Letter (sealed)')),
          const SizedBox(height: 6),
          Text(left < 0 ? 'Too long by ${-left} characters' : '$left characters left in this envelope${photo != null ? ' with the picture' : ''}',
              style: TextStyle(fontSize: 12.5, color: left < 0 ? Palette.band : const Color(0xFF6F7883))),
          const SizedBox(height: 12),
          if (parcelBytes != null)
            Card(
              child: ListTile(
                leading: const Icon(Icons.inventory_2_outlined, color: Palette.brass),
                title: Text(parcelName ?? 'parcel'),
                subtitle: Text('${formatBytes(parcelBytes!.length)} · ${terms == null ? 'price unknown' : '${formatBerry(terms!.priceFor(parcelBytes!.length + 64))} BERRY'} to the parcel room, kept ${terms?.ttlDays ?? 30} days'),
                trailing: IconButton(icon: const Icon(Icons.close), onPressed: () => setState(() { parcelBytes = null; parcelName = null; })),
              ),
            ),
          if (photo != null)
            Stack(
              alignment: Alignment.topRight,
              children: [
                ClipRRect(borderRadius: BorderRadius.circular(10), child: Image.memory(photo!, height: 160, fit: BoxFit.cover, width: double.infinity)),
                IconButton.filled(
                    icon: const Icon(Icons.close),
                    onPressed: () {
                      setState(() => photo = null);
                      _changed();
                    }),
              ],
            )
          else
            Row(children: [
              Expanded(child: OutlinedButton.icon(icon: const Icon(Icons.photo_camera_outlined), label: const Text('Take a picture'), onPressed: () => takePhoto(ImageSource.camera))),
              const SizedBox(width: 10),
              Expanded(child: OutlinedButton.icon(icon: const Icon(Icons.photo_library_outlined), label: const Text('From gallery'), onPressed: () => takePhoto(ImageSource.gallery))),
            ]),
          if (photo != null) Padding(padding: const EdgeInsets.only(top: 6), child: Text('${photo!.length ~/ 1024} KB picture, sealed with the words. One per letter.', style: const TextStyle(fontSize: 12.5, color: Color(0xFF6F7883)))),
          const SizedBox(height: 12),
          TextField(controller: amount, keyboardType: const TextInputType.numberWithOptions(decimal: true), decoration: InputDecoration(labelText: g == null ? 'BERRY to send with it (optional)' : 'BERRY to send with each copy (optional)')),
          const SizedBox(height: 16),
          FilledButton.icon(icon: const Icon(Icons.lock_outline), label: Text(g == null ? 'Seal and send' : 'Seal and send to $copies people'), onPressed: left < 0 ? null : send),
          const SizedBox(height: 12),
          Text(
            g == null
                ? 'Fee ${formatBerry(fee)} BERRY. Only the recipient can read this; the ledger shows the two addresses, the time and the size. Drafts are kept on this phone until you send or discard them.'
                : 'One sealed copy per person, ${formatBerry(fee)} BERRY each. Each copy carries the crew so they can reply to everyone. The ledger shows you writing to $copies addresses.',
            style: const TextStyle(color: Color(0xFF6F7883), fontSize: 13),
          ),
        ],
      ),
    );
  }
}


/// A parcel named in a letter: fetch it from the room, check it, hand it over.
class _ParcelCard extends StatefulWidget {
  final ParcelRef ref;
  const _ParcelCard(this.ref);
  @override
  State<_ParcelCard> createState() => _ParcelCardState();
}

class _ParcelCardState extends State<_ParcelCard> {
  Uint8List? bytes;
  String? error;
  bool busy = false;

  Future<void> fetch() async {
    final s = SessionScope.of(context);
    setState(() { busy = true; error = null; });
    try {
      bytes = await s.fetchParcelBytes(widget.ref);
    } catch (e) {
      error = '$e'.replaceFirst(RegExp(r'^\w+Error: '), '');
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final r = widget.ref;
    return Card(
      color: const Color(0xFFFBF1DC),
      child: Padding(
        padding: const EdgeInsets.fromLTRB(16, 12, 16, 12),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(children: [
              const Icon(Icons.inventory_2_outlined, color: Palette.brass),
              const SizedBox(width: 8),
              Expanded(child: Text(r.name, style: const TextStyle(fontWeight: FontWeight.w600))),
              Text(formatBytes(r.size), style: const TextStyle(color: Color(0xFF6F7883), fontSize: 13)),
            ]),
            const SizedBox(height: 6),
            Text(bytes == null
                ? 'A parcel, sealed on the sender\'s phone or PC and kept by a parcel room for a while. Fetch it to open it here.'
                : 'Fetched and checked: the bytes match the letter.', style: const TextStyle(fontSize: 13, height: 1.4)),
            if (error != null) Padding(padding: const EdgeInsets.only(top: 6), child: Text(error!, style: const TextStyle(color: Palette.band, fontSize: 13))),
            const SizedBox(height: 8),
            // The theme gives filled buttons a full-width minimum size; inside a Row
            // they must be allowed that width or Android lays them out with none.
            Row(children: [
              if (bytes == null)
                Expanded(child: FilledButton.tonal(onPressed: busy ? null : fetch, child: busy ? const SizedBox(width: 16, height: 16, child: CircularProgressIndicator(strokeWidth: 2)) : const Text('Fetch'))),
              if (bytes != null)
                Expanded(
                  child: FilledButton.icon(
                    icon: const Icon(Icons.save_alt),
                    label: Text(isBrowser ? 'Download' : 'Save or share'),
                    onPressed: () => saveBytes(r.name, bytes!),
                  ),
                ),
            ]),
          ],
        ),
      ),
    );
  }
}
