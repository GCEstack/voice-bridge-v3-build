from unittest.mock import patch

from src.keyboard_input import type_text, press_enter


@patch("src.keyboard_input.keyboard")
def test_type_text_sends_keys(mock_keyboard):
    type_text("hi", interval=0)
    mock_keyboard.write.assert_called_once_with("hi", delay=0)


@patch("src.keyboard_input.keyboard")
def test_press_enter_sends_return(mock_keyboard):
    press_enter()
    mock_keyboard.press_and_release.assert_called_once_with("return")
