import 'dart:ui' show Tristate;

import 'package:flutter/foundation.dart';
import 'package:flutter/semantics.dart';
import 'package:flutter/widgets.dart';
import 'package:marionette_flutter/marionette_flutter.dart';

SemanticsHandle? _automationSemantics;

/// Read-only instrumentation. Kept out of profile/release initialization.
void registerAutomationSemantics() {
  if (!kDebugMode) return;
  _automationSemantics ??= WidgetsBinding.instance.ensureSemantics();
  registerMarionetteExtension(
    name: 'e2e_snapshot',
    description: 'Read identified accessibility nodes for semantic E2E tests.',
    callback: (_) async {
      // endOfFrame requests a frame when idle and waits for semantics to update.
      await WidgetsBinding.instance.endOfFrame;
      return MarionetteExtensionResult.success(captureSemanticSnapshot());
    },
  );
}

/// Exports the actual semantics tree, including merged labels and values.
///
/// Only explicitly identified nodes enter the automation contract. To make a
/// node tappable with Marionette 0.6, give its control a `ValueKey<String>` equal
/// to its Semantics.identifier. Keys must be unique across the mounted app.
Map<String, dynamic> captureSemanticSnapshot() {
  final binding = WidgetsBinding.instance;
  final keys = <String, int>{};
  void visitElement(Element element) {
    if (element.widget.key case ValueKey<String>(:final value)) {
      keys.update(value, (count) => count + 1, ifAbsent: () => 1);
    }
    element.visitChildren(visitElement);
  }

  binding.rootElement?.visitChildren(visitElement);
  final nodes = <Map<String, dynamic>>[];
  void visitNode(SemanticsNode node, String? parent) {
    if (node.isMergedIntoParent) return;
    final data = node.getSemanticsData();
    final flags = data.flagsCollection;
    if (flags.isHidden || node.rect.isEmpty) return;
    var nextParent = parent;
    if (data.identifier.isNotEmpty) {
      nextParent = data.identifier;
      final enabled = flags.isEnabled != Tristate.isFalse;
      final keyCount = keys[data.identifier] ?? 0;
      nodes.add({
        'id': data.identifier,
        'parent': parent,
        'label': data.label.isNotEmpty ? data.label : data.tooltip,
        'value': flags.isObscured ? '<redacted>' : data.value,
        'role': flags.isButton
            ? 'button'
            : flags.isTextField
            ? 'textField'
            : 'content',
        'enabled': enabled,
        'focused': flags.isFocused == Tristate.isTrue,
        'obscured': flags.isObscured,
        'is_empty': data.value.isEmpty,
        'key_count': keyCount,
        'actions': [
          if (enabled && keyCount == 1 && data.hasAction(SemanticsAction.tap))
            'tap',
          if (enabled &&
              keyCount == 1 &&
              flags.isTextField &&
              !flags.isReadOnly &&
              (data.hasAction(SemanticsAction.tap) ||
                  data.hasAction(SemanticsAction.setText)))
            // fill includes focusing the field first; Flutter may only
            // advertise its native setText action after it gains focus.
            'fill',
        ],
      });
    }
    node.visitChildren((child) {
      visitNode(child, nextParent);
      return true;
    });
  }

  for (final view in binding.renderViews) {
    final root = view.owner?.semanticsOwner?.rootSemanticsNode;
    if (root != null) visitNode(root, null);
  }
  return {'schema_version': 1, 'nodes': nodes};
}
