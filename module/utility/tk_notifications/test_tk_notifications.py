"""Tk通知ユーティリティの公開関数を単体検証する。"""

import unittest
from unittest.mock import MagicMock, call, patch

from module.utility.tk_notifications import tk_notifications


class TkNotificationsTests(unittest.TestCase):
    def setUp(self):
        self.parent = MagicMock()
        self.master_root = MagicMock()

    def test_show_info_logs_and_forwards_dialog_arguments(self):
        with patch.object(tk_notifications.logger, "info") as log_info:
            with patch.object(tk_notifications.messagebox, "showinfo") as showinfo:
                tk_notifications.show_info("情報", "処理が完了しました。", self.parent)

        log_info.assert_called_once_with(
            "GUI情報メッセージ: 情報 - 処理が完了しました。"
        )
        showinfo.assert_called_once_with(
            "情報", "処理が完了しました。", parent=self.parent
        )

    def test_show_warning_logs_and_forwards_dialog_arguments(self):
        with patch.object(tk_notifications.logger, "warning") as log_warning:
            with patch.object(tk_notifications.messagebox, "showwarning") as showwarning:
                tk_notifications.show_warning("警告", "入力を確認してください。", self.parent)

        log_warning.assert_called_once_with(
            "GUI警告メッセージ: 警告 - 入力を確認してください。"
        )
        showwarning.assert_called_once_with(
            "警告", "入力を確認してください。", parent=self.parent
        )

    def test_show_error_logs_and_forwards_dialog_arguments(self):
        with patch.object(tk_notifications.logger, "error") as log_error:
            with patch.object(tk_notifications.messagebox, "showerror") as showerror:
                tk_notifications.show_error("エラー", "保存に失敗しました。", self.parent)

        log_error.assert_called_once_with(
            "GUIエラーメッセージ: エラー - 保存に失敗しました。"
        )
        showerror.assert_called_once_with(
            "エラー", "保存に失敗しました。", parent=self.parent
        )

    def test_ask_yes_no_forwards_arguments_and_returns_each_answer(self):
        with patch.object(tk_notifications.logger, "info") as log_info:
            with patch.object(
                tk_notifications.messagebox, "askyesno", side_effect=[True, False]
            ) as askyesno:
                yes_answer = tk_notifications.ask_yes_no(
                    "確認", "続行しますか？", self.parent
                )
                no_answer = tk_notifications.ask_yes_no(
                    "確認", "もう一度確認しますか？", self.parent
                )

        self.assertIs(yes_answer, True)
        self.assertIs(no_answer, False)
        self.assertEqual(
            askyesno.call_args_list,
            [
                call("確認", "続行しますか？", parent=self.parent),
                call("確認", "もう一度確認しますか？", parent=self.parent),
            ],
        )
        self.assertEqual(
            log_info.call_args_list,
            [
                call("GUI確認ダイアログ: 確認 - 続行しますか？"),
                call("GUI確認ダイアログ: 確認 - もう一度確認しますか？"),
            ],
        )

    def test_ask_string_forwards_options_and_returns_entered_value(self):
        with patch.object(tk_notifications.logger, "info") as log_info:
            with patch.object(
                tk_notifications.simpledialog,
                "askstring",
                return_value="入力された値",
            ) as askstring:
                result = tk_notifications.ask_string(
                    "APIキー", "APIキーを入力してください。",
                    initialvalue="初期値", show="", parent=self.parent
                )

        self.assertEqual(result, "入力された値")
        askstring.assert_called_once_with(
            "APIキー", "APIキーを入力してください。",
            initialvalue="初期値", show="", parent=self.parent
        )
        log_info.assert_called_once_with(
            "GUI文字列入力ダイアログ: APIキー - APIキーを入力してください。"
        )

    def test_ask_string_preserves_none_when_cancelled(self):
        with patch.object(
            tk_notifications.simpledialog, "askstring", return_value=None
        ) as askstring:
            result = tk_notifications.ask_string(
                "APIキー", "APIキーを入力してください。", parent=self.parent
            )

        self.assertIsNone(result)
        askstring.assert_called_once_with(
            "APIキー", "APIキーを入力してください。",
            initialvalue=None, show="*", parent=self.parent
        )

    def test_empty_file_options_warn_and_return_none(self):
        with patch.object(tk_notifications, "show_warning") as show_warning:
            with patch.object(tk_notifications.tk, "Toplevel") as toplevel:
                result = tk_notifications.show_file_selection_dialog(
                    self.master_root, "ファイルを選択", []
                )

        self.assertIsNone(result)
        show_warning.assert_called_once_with(
            "ファイルが見つかりません",
            "開くべきファイルが指定されていません。",
            parent=self.master_root,
        )
        toplevel.assert_not_called()

    def test_single_file_option_shows_information_and_returns_path(self):
        path = "C:/test/video.json"
        with patch.object(tk_notifications, "show_info") as show_info:
            with patch.object(tk_notifications.tk, "Toplevel") as toplevel:
                result = tk_notifications.show_file_selection_dialog(
                    self.master_root, "ファイルを選択", [("動画情報", path)]
                )

        self.assertEqual(result, path)
        show_info.assert_called_once_with(
            "ファイルを開く",
            "動画情報 (video.json) を開きます。",
            parent=self.master_root,
        )
        toplevel.assert_not_called()

    def test_multiple_file_options_build_dialog_and_return_selected_path(self):
        first_path = "C:/test/first.json"
        second_path = "C:/test/second.json"
        choice_window = MagicMock()
        selected_path = MagicMock()
        selected_path.get.return_value = second_path
        label_widget = MagicMock()
        radio_widget = MagicMock()
        button_widget = MagicMock()

        with patch.object(
            tk_notifications.tk, "Toplevel", return_value=choice_window
        ) as toplevel:
            with patch.object(
                tk_notifications.tk, "Label", return_value=label_widget
            ) as label_factory:
                with patch.object(
                    tk_notifications.tk, "Radiobutton", return_value=radio_widget
                ) as radio_factory:
                    with patch.object(
                        tk_notifications.tk, "Button", return_value=button_widget
                    ) as button_factory:
                        with patch.object(
                            tk_notifications.tk, "StringVar", return_value=selected_path
                        ) as string_var:
                            def select_second_file(window):
                                self.assertIs(window, choice_window)
                                button_factory.call_args.kwargs["command"]()

                            self.master_root.wait_window.side_effect = select_second_file
                            result = tk_notifications.show_file_selection_dialog(
                                self.master_root,
                                "ファイルを選択",
                                [("最初の動画", first_path), ("次の動画", second_path)],
                            )

        self.assertEqual(result, second_path)
        toplevel.assert_called_once_with(self.master_root)
        choice_window.title.assert_called_once_with("ファイルを選択")
        choice_window.geometry.assert_called_once_with("400x200")
        choice_window.transient.assert_called_once_with(self.master_root)
        choice_window.grab_set.assert_called_once_with()
        label_factory.assert_called_once_with(
            choice_window, text="開きたいファイルを選択してください:"
        )
        label_widget.pack.assert_called_once_with(pady=10)
        string_var.assert_called_once_with(choice_window)
        selected_path.set.assert_called_once_with(first_path)
        self.assertEqual(
            radio_factory.call_args_list,
            [
                call(
                    choice_window,
                    text="最初の動画 (first.json)",
                    variable=selected_path,
                    value=first_path,
                ),
                call(
                    choice_window,
                    text="次の動画 (second.json)",
                    variable=selected_path,
                    value=second_path,
                ),
            ],
        )
        self.assertEqual(radio_widget.pack.call_args_list, [
            call(anchor="w", padx=20),
            call(anchor="w", padx=20),
        ])
        button_factory.assert_called_once_with(
            choice_window, text="開く", command=button_factory.call_args.kwargs["command"]
        )
        button_widget.pack.assert_called_once_with(pady=10)
        self.master_root.wait_window.assert_called_once_with(choice_window)
        choice_window.destroy.assert_called_once_with()

    def test_multiple_file_options_return_none_when_dialog_is_cancelled(self):
        choice_window = MagicMock()
        button_widget = MagicMock()

        with patch.object(
            tk_notifications.tk, "Toplevel", return_value=choice_window
        ):
            with patch.object(tk_notifications.tk, "Label"):
                with patch.object(tk_notifications.tk, "Radiobutton"):
                    with patch.object(
                        tk_notifications.tk, "Button", return_value=button_widget
                    ):
                        with patch.object(tk_notifications.tk, "StringVar"):
                            result = tk_notifications.show_file_selection_dialog(
                                self.master_root,
                                "ファイルを選択",
                                [("動画A", "C:/test/a.json"), ("動画B", "C:/test/b.json")],
                            )

        self.assertIsNone(result)
        button_widget.pack.assert_called_once_with(pady=10)
        choice_window.destroy.assert_not_called()
        self.master_root.wait_window.assert_called_once_with(choice_window)


if __name__ == "__main__":
    unittest.main()
