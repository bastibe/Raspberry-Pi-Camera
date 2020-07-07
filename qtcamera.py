# You need to set the memory split in raspi-config, advanced to 256
# for the highest resolution capture to work.

from PySide2 import QtCore
from PySide2 import QtWidgets
from PySide2 import QtGui
from picamera.array import PiRGBArray
from picamera import PiCamera
import time
import sys

class Viewfinder(QtWidgets.QWidget):
    closeWindow = QtCore.Signal()

    def __init__(self, parent, width, height):
        super().__init__(parent)
        self.size = (width, height)

        # initialize the camera:
        self.camera = PiCamera()
        self.camera.resolution = self.size
        self.camera.framerate = 30
        self.setCursor(QtCore.Qt.BlankCursor)

    def paintEvent(self, event):
        with PiRGBArray(self.camera) as output:
            self.camera.capture(output, 'rgb', use_video_port=True)
            image = QtGui.QImage(output.array, *self.size, self.size[0]*3, QtGui.QImage.Format_RGB888)

        painter = QtGui.QPainter(self)
        painter.drawImage(self.rect(), image)
        self.update()

    def mousePressEvent(self, event):
        # top right corner: close
        if event.x() > (self.size[0] - 40) and event.y() < 40:
            self.closeWindow.emit()
        # horizontal center: take a picture
        if event.x() > 200 and event.x() < (self.size[0] - 200):
            self.takePicture()

    def takePicture(self):
        # set highest possible resolution:
        self.camera.resolution = self.camera.MAX_RESOLUTION

        with PiRGBArray(self.camera) as output:
            self.camera.capture(output, 'rgb')
            image = output.array
        print(image.shape); sys.stdout.flush()

        # reset to old resolution:
        self.camera.resolution = self.size
        self.camera.framerate = 30


class FullScreenWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__(flags=QtCore.Qt.FramelessWindowHint)
        self.setWindowTitle("Viewfinder")

        screensize = app.desktop().availableGeometry()
        screenwidth = screensize.x() + screensize.width()
        screenheight = screensize.y() + screensize.height()

        main_widget = Viewfinder(self, screenwidth, screenheight)
        self.setCentralWidget(main_widget)
        main_widget.closeWindow.connect(self.close)

        self.setGeometry(QtCore.QRect(0, 0, screenwidth, screenheight))


if __name__ == "__main__":
    app = QtWidgets.QApplication(sys.argv)
    window = FullScreenWindow()
    window.show()
    sys.exit(app.exec_())
