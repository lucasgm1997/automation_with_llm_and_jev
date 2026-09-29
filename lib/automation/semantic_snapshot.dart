import 'dart:ui' show Tristate;

import 'package:flutter/foundation.dart';
import 'package:flutter/semantics.dart';
import 'package:flutter/widgets.dart';
import 'package:marionette_flutter/marionette_flutter.dart';

SemanticsHandle? _automationSemantics;

/// Semantic observation and interaction, only registered in debug builds.
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
  registerMarionetteExtension(
    name: 'e2e_action',
    description: 'Tap or focus a control by its unique Semantics.identifier.',
    callback: (params) async {
      final identifier = params['identifier'];
      final operation = params['operation'];
      if (identifier == null ||
          identifier.isEmpty ||
          (operation != 'tap' && operation != 'focus')) {
        return const MarionetteExtensionResult.invalidParams(
          'Provide identifier and operation (tap or focus).',
        );
      }
      await WidgetsBinding.instance.endOfFrame;
      try {
        performSemanticInteraction(identifier, operation!);
        return const MarionetteExtensionResult.success({'performed': true});
      } on StateError catch (error) {
        return MarionetteExtensionResult.error(0, error.message);
      }
    },
  );
}

typedef _Target = ({SemanticsOwner owner, SemanticsNode node, String? parent});

List<_Target> _identifiedTargets() {
  final targets = <_Target>[];
  void visitNode(SemanticsOwner owner, SemanticsNode node, String? parent) {
    if (node.isMergedIntoParent) return;
    final data = node.getSemanticsData();
    final flags = data.flagsCollection;
    if (flags.isHidden || node.rect.isEmpty) return;
    var nextParent = parent;
    if (data.identifier.isNotEmpty) {
      nextParent = data.identifier;
      targets.add((owner: owner, node: node, parent: parent));
    }
    node.visitChildren((child) {
      visitNode(owner, child, nextParent);
      return true;
    });
  }

  for (final view in WidgetsBinding.instance.renderViews) {
    final owner = view.owner?.semanticsOwner;
    final root = owner?.rootSemanticsNode;
    if (owner != null && root != null) visitNode(owner, root, null);
  }
  return targets;
}

/// Exports identified accessibility nodes. No widget key is required.
Map<String, dynamic> captureSemanticSnapshot() {
  final nodes = <Map<String, dynamic>>[];
  for (final target in _identifiedTargets()) {
    final data = target.node.getSemanticsData();
    final flags = data.flagsCollection;
    final enabled = flags.isEnabled != Tristate.isFalse;
    nodes.add({
      'id': data.identifier,
      'parent': target.parent,
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
      'actions': [
        if (enabled && data.hasAction(SemanticsAction.tap)) 'tap',
        if (enabled &&
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
  return {'schema_version': 2, 'nodes': nodes};
}

/// Dispatches the same tap action used by accessibility services.
///
/// Resolves the live tree again before acting. The identifier must select
/// exactly one accessible, enabled node that advertises the requested action.
/// This exercises semantic callbacks, not physical pointer hit testing.
void performSemanticInteraction(String identifier, String operation) {
  if (!kDebugMode) throw StateError('Automation requires a debug build.');
  if (operation != 'tap' && operation != 'focus') {
    throw StateError('Unsupported semantic operation.');
  }
  final matches = _identifiedTargets()
      .where(
        (target) => target.node.getSemanticsData().identifier == identifier,
      )
      .toList();
  if (matches.length != 1) {
    throw StateError('Expected exactly one accessible semantic target.');
  }
  final target = matches.single;
  final data = target.node.getSemanticsData();
  final flags = data.flagsCollection;
  if (flags.isEnabled == Tristate.isFalse) {
    throw StateError('Semantic target is disabled.');
  }
  if (operation == 'focus') {
    if (!flags.isTextField || flags.isReadOnly) {
      throw StateError('Semantic target is not an editable field.');
    }
    if (flags.isFocused == Tristate.isTrue) return;
  }
  if (!data.hasAction(SemanticsAction.tap)) {
    throw StateError('Semantic target does not expose a tap action.');
  }
  target.owner.performAction(target.node.id, SemanticsAction.tap);
}
