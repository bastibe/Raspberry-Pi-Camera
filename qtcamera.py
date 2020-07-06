from PySide2 import QtCore
from PySide2 import QtWidgets
from PySide2 import QtGui
from picamera.array import PiRGBArray
from picamera import PiCamera
import time
import sys

class Viewfinder(QtWidgets.QWidget):
    def __init__(self, parent):
        super().__init__(parent)
        # initialize the camera:
        self.camera = PiCamera()
        self.camera.resolution = (640, 480)
        self.camera.framerate = 60

    def paintEvent(self, event):
        with PiRGBArray(self.camera) as output:
            self.camera.capture(output, 'rgb', use_video_port=True)
            image = QtGui.QImage(output.array, 640, 480, 640*3, QtGui.QImage.Format_RGB888)

        painter = QtGui.QPainter(self)
        painter.drawImage(self.rect(), image)
        self.update()

    def sizeHint(self):
        return QtCore.QSize(640, 480)


class MainWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Viewfinder")

        main_widget = Viewfinder(self)
        self.setCentralWidget(main_widget)

if __name__ == "__main__":
    app = QtWidgets.QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())
