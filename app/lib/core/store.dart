// Where the app keeps its small files: the sealed wallet, settings, contacts
// and the header window. On a phone these are real files in the app's
// documents directory. In the browser they live in localStorage under the
// same names, so the rest of the app never needs to know which it is.
export 'store_io.dart' if (dart.library.js_interop) 'store_web.dart';
