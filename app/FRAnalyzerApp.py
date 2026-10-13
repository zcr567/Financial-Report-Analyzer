
from kivy.config import Config
Config.set('graphics', 'width', '1920')
Config.set('graphics', 'height', '1280')

from kivy.core.window import Window
Window.minimum_height = 400
Window.minimum_width = 400

from kivy.app import App
from kivy.uix.boxlayout import BoxLayout

class MainWidget(BoxLayout):
    pass

class FRAnalyzerApp(App):
    def build(self):
        return MainWidget()

if __name__ == "__main__":
    FRAnalyzerApp().run()