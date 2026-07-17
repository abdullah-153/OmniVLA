class UIElement:
    def __init__(self, label=None, role=None, bounding_box=None):
        self.label = label
        self.role = role
        self.bounding_box = bounding_box

class SemanticState:
    def __init__(
        self,
        app="unknown",
        window_title="",
        elements=None,
        layout_type="default",
        is_dialog=False,
        visible_text_summary="",
        is_available=False,
        source="",
    ):
        self.app = app
        self.window_title = window_title
        self.elements = elements if elements is not None else []
        self.layout_type = layout_type
        self.is_dialog = is_dialog
        self.visible_text_summary = visible_text_summary
        self.is_available = is_available
        self.source = source

class AgentAction:
    def __init__(self, action_type="click", thought="", args=None):
        self.action_type = action_type
        self.thought = thought
        self.args = args if args is not None else []
