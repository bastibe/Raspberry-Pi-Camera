# You need to set the memory split in raspi-config, advanced to 256
# for the highest resolution capture to work.

import sys
import time
import argparse
import textwrap
import pathlib
import threading
import gpiozero
from PySide2 import QtCore
from PySide2 import QtWidgets
from PySide2 import QtGui
from picamera.array import PiRGBArray
from picamera import PiCamera


class ValueSlider(QtWidgets.QWidget):
    valueChanged = QtCore.Signal(int)

    def __init__(self, parent, name, steps, index=None):
        super().__init__(parent)
        self.steps = steps
        self.index = index
        self.name = name
        self.dragOrigin = None
        self.offset = 0

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        pen = QtGui.QPen("white")
        pen.setWidth(2)
        painter.setPen(pen)

        font = self.font()
        font.setPixelSize(40)
        painter.setFont(font)

        painter.drawText(0, 0, self.width(), 40,
                         QtCore.Qt.AlignHCenter | QtCore.Qt.AlignVCenter,
                         self.name)

        font = self.font()
        font.setPixelSize(34)
        painter.setFont(font)

        painter.setClipRect(0, 40, self.width(), self.height()-40)
        for idx in range(len(self.steps)):
            y = 40 * (idx - self.index) + self.height()/2 - 20 + self.offset
            font = self.font()
            font.setBold(idx == self.index)
            painter.setFont(font)
            painter.drawText(0, y, self.width(), 40,
                             QtCore.Qt.AlignHCenter | QtCore.Qt.AlignVCenter,
                             str(self.steps[idx]) if self.steps[idx] != 0 else "Auto")
        painter.drawRect(0, self.height()/2-20, self.width(), 40)

    def increment(self, increment):
        index = self.index + increment
        if index < 0:
            index = 0
        if index >= len(self.steps):
            index = len(self.steps) - 1

        index_delta = self.index - index
        if index_delta != 0:
            self.index = index
            self.valueChanged.emit(self.value)

    def mousePressEvent(self, event):
        self.dragOrigin = event.y()

    def mouseMoveEvent(self, event):
        self.offset = event.y() - self.dragOrigin
        index = round(self.index - self.offset / 40)
        if index < 0:
            index = 0
        if index >= len(self.steps):
            index = len(self.steps) - 1

        index_delta = self.index - index
        if index_delta != 0:
            self.index = index
            self.valueChanged.emit(self.value)

        self.offset -= 40 * index_delta
        self.dragOrigin += 40 * index_delta

    def mouseReleaseEvent(self, event):
        offset = event.y() - self.dragOrigin

        if offset == 0: # a click
            offset = self.height()/2 - event.y()

        index = round(self.index - offset / 40)
        if index < 0:
            index = 0
        if index >= len(self.steps):
            index = len(self.steps) - 1

        index_delta = self.index - index
        if index_delta != 0:
            self.index = index
            self.valueChanged.emit(self.value)

        self.offset = 0
        self.dragOrigin = None

    @property
    def value(self):
        return self.steps[self.index]

import io
class CaptureThread(threading.Thread):
    def __init__(self, camera):
        super().__init__()
        self.camera = camera
        width, height = self.camera.resolution
        self.last_capture = bytearray(width * height * 3)
        self.should_stop = False
        self.should_pause = False

    def run(self):
        stream = io.BytesIO()
        while True:
            if self.should_pause:
                time.sleep(0.1)
                continue
            for _ in self.camera.capture_continuous(stream, format='rgb', use_video_port=True):
                stream.seek(0)
                stream.readinto1(self.last_capture)
                stream.truncate()
                stream.seek(0)
                if self.should_stop or self.should_pause:
                    break
            if self.should_stop:
                break

    def stop(self):
        self.should_stop = True

    def pause(self):
        self.should_pause = True
        time.sleep(0.1) # wait for capturing to stop

    def unpause(self):
        self.should_pause = False


class Viewfinder(QtWidgets.QWidget):
    closeWindow = QtCore.Signal()

    def __init__(self, parent, width, height, output_path, file_prefix):
        super().__init__(parent)
        self.size = (width, height)
        self.output_path = pathlib.Path(output_path).expanduser()
        self.file_prefix = file_prefix

        # exposure_compensation
        shutter_speeds = [0, 8, 15, 30, 60, 125, 250, 500, 1000, 2000, 4000, 8000]
        self.shutter_slider = ValueSlider(self, "Shutter", shutter_speeds , 0)
        self.shutter_slider.setGeometry(0, 40, 200, height-80)
        self.shutter_slider.valueChanged.connect(self.setShutterSpeed)

        isos = [0, 100, 200, 320, 400, 640, 800, 1600]
        self.iso_slider = ValueSlider(self, "ISO", isos, 0)
        self.iso_slider.setGeometry(width-200, 40, 200, height-80)
        self.iso_slider.valueChanged.connect(self.setISO)

        # initialize the camera:
        self.camera = PiCamera()
        self.camera.resolution = self.size
        self.camera.framerate = 30

        # connect the physical shutter button:
        self.shutterButton = gpiozero.Button(4)
        self.shutterButton.when_pressed = self.takePicture
        # connect the physical shutter encoder:
        self.shutterEncoder1 = gpiozero.Button(17, pull_up=False)
        self.shutterEncoder2 = gpiozero.Button(18, pull_up=False)
        self.shutterEncoder1.when_pressed = self.shutterEncoderEvent
        self.shutterEncoder2.when_pressed = self.shutterEncoderEvent
        # connect the physical ISO encoder:
        self.isoEncoder1 = gpiozero.Button(22, pull_up=False)
        self.isoEncoder2 = gpiozero.Button(23, pull_up=False)
        self.isoEncoder1.when_pressed = self.isoEncoderEvent
        self.isoEncoder2.when_pressed = self.isoEncoderEvent

        # keep redrawing:
        self.setCursor(QtCore.Qt.BlankCursor)
        self.paintScheduler = QtCore.QTimer(self)
        self.paintScheduler.setInterval(1/60*1000)
        self.paintScheduler.setSingleShot(False)
        self.paintScheduler.timeout.connect(self.update)
        self.paintScheduler.start()

        self.recorder = CaptureThread(self.camera)
        self.recorder.start()

    def shutterEncoderEvent(self):
        increment = self.shutterEncoder1.value - self.shutterEncoder2.value
        if increment != 0:
            self.shutter_slider.increment(increment)

    def isoEncoderEvent(self):
        increment = self.isoEncoder1.value - self.isoEncoder2.value
        if increment != 0:
            self.iso_slider.increment(increment)

    def paintEvent(self, event):
        image = QtGui.QImage(self.recorder.last_capture, *self.size, self.size[0]*3, QtGui.QImage.Format_RGB888)

        painter = QtGui.QPainter(self)
        painter.drawImage(self.rect(), image)

        pen = QtGui.QPen("white")
        pen.setWidth(2)
        painter.setPen(pen)

        font = self.font()
        font.setPixelSize(30)
        painter.setFont(font)

        painter.drawText(0, self.height()-40, 200, 40,
                         QtCore.Qt.AlignHCenter | QtCore.Qt.AlignVCenter,
                         f'{str(self.camera.exposure_speed/1e6)} s')
        painter.drawText(self.width()-200, self.height()-40, 200, 40,
                         QtCore.Qt.AlignHCenter | QtCore.Qt.AlignVCenter,
                         f'{str(self.camera.analog_gain * self.camera.digital_gain)}')


    def mousePressEvent(self, event):
        # top right corner: close
        if event.x() > (self.size[0] - 40) and event.y() < 40:
            self.recorder.stop()
            self.recorder.join(0.1)
            self.closeWindow.emit()
        # horizontal center: take a picture
        if event.x() > 200 and event.x() < (self.size[0] - 200):
            self.takePicture()

    def takePicture(self):
        # pause live view, as we can't have multiple threads
        # reading from the same sensor:
        self.recorder.pause()

        # save off previous framerate, as the resolution change
        # might change it:
        old_framerate = self.camera.framerate

        # set highest possible resolution:
        self.camera.resolution = self.camera.MAX_RESOLUTION

        try:
            image_files = list(self.output_path.glob(f'{self.file_prefix}*.jpg'))
            if image_files:
                last_file = sorted(image_files)[-1]
                last_index = int(last_file.name[len(self.file_prefix):-4])
            else:
                last_index = 0
            new_file = self.output_path / f'{self.file_prefix}{last_index+1:04d}.jpg'
            print(f'saving image to {new_file}')
            sys.stdout.flush()
            with new_file.open('wb') as f:
                self.camera.capture(f, format='jpeg', bayer=True)
        except Exception as err:
            print('Error saving image:', err)

        # reset to old resolution and framerate:
        self.camera.resolution = self.size
        self.camera.framerate = old_framerate

        # unpause live view:
        self.recorder.unpause()

    def setISO(self, iso):
        self.camera.iso = iso

    def setShutterSpeed(self, shutter_speed):
        if shutter_speed == 0:
            self.camera.shutter_speed = 0
            self.camera.framerate = 30
            return

        new_speed = int(1e6/shutter_speed)
        old_speed = self.camera.exposure_speed

        if shutter_speed > 30:
            self.camera.shutter_speed = new_speed
        else:
            self.camera.framerate = shutter_speed
            self.camera.shutter_speed = new_speed


class RaspiCamera(QtWidgets.QMainWindow):
    def __init__(self, output_path, file_prefix):
        super().__init__(flags=QtCore.Qt.FramelessWindowHint)
        self.setWindowTitle("Viewfinder")

        screensize = app.desktop().availableGeometry()
        screenwidth = screensize.x() + screensize.width()
        screenheight = screensize.y() + screensize.height()

        main_widget = Viewfinder(self, screenwidth, screenheight, output_path, file_prefix)
        self.setCentralWidget(main_widget)
        main_widget.closeWindow.connect(self.close)

        self.setGeometry(QtCore.QRect(0, 0, screenwidth, screenheight))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=textwrap.dedent("""
        Shows a full screen window that transforms the Raspberry Pi into a camera.

        The app is meant to be used with a touch screen. No mouse cursor is shown.
        Tap the top right corner to exit the app.
        Tap the center to take a picture.
        """))
    parser.add_argument('--output-path', '-p', help="Where to save pictures", default="~/Pictures/")
    parser.add_argument('--file-prefix', '-f', help="Beginning of file name", default="RPCAM")
    args = parser.parse_args()

    app = QtWidgets.QApplication(sys.argv)
    window = RaspiCamera(output_path=args.output_path, file_prefix=args.file_prefix)
    window.show()
    sys.exit(app.exec_())
