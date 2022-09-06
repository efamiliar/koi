from dataclasses import dataclass
from PyQt5.QtWidgets import *
from PyQt5.QtCore import *
from PyQt5.QtGui import QImage
from krita import DockWidget, Krita
from urllib import request, parse
from io import BytesIO
import json
import base64
import requests


sizes = ["DDIM", "PLMS", 'k_dpm_2_a', 'k_dpm_2', 'k_euler_a', 'k_euler', 'k_heun', 'k_lms']


class Koi(DockWidget):
    def __init__(self):
        """
        This sets up a basic user interface to interact with.

        TODO/FIXME: Adopt a better approach for managing the UI.
        """
        super().__init__()
        self.ITER = 0

        self.setWindowTitle("Koi")

        # Main WIdget ===
        self.mainWidget = QWidget(self)
        self.mainWidget.setLayout(QVBoxLayout())
        self.setWidget(self.mainWidget)

        # Input & Prompt Settings ===
        self.input_widget = QWidget(self.mainWidget)

        self.input_layout = QFormLayout()

        self.prompt = QLineEdit()
        self.prompt.setPlaceholderText("Describe your end goal...")
        self.prompt.setText(
            "A beautiful mountain landscape in the style of greg rutkowski, oils on canvas."
        )
    

        self.steps = QSpinBox(self.input_widget)
        self.steps.setRange(5, 150)
        self.steps.setValue(50)

        self.seed = QLineEdit(self.input_widget)
        self.prompt.setPlaceholderText("Optional seed")
        self.seed.setText("")

        self.sketch_strengh = QDoubleSpinBox(self.input_widget)
        self.sketch_strengh.setRange(0.05, 0.95)
        self.sketch_strengh.setSingleStep(0.05)
        self.sketch_strengh.setValue(0.25)

        self.prompt_strength = QDoubleSpinBox(self.input_widget)
        self.prompt_strength.setRange(1.0, 20.00)
        self.prompt_strength.setValue(7.5)

        self.input_layout.addRow("Prompt", self.prompt)
        self.input_layout.addRow("Steps", self.steps)
        self.input_layout.addRow("Seed", self.seed)
        self.input_layout.addRow("Sketch strength", self.sketch_strengh)
        self.input_layout.addRow("Prompt strength", self.prompt_strength)

        self.input_widget.setLayout(self.input_layout)

        self.mainWidget.layout().addWidget(self.input_widget)

        # Endpoint Settings ===
        self.endpoint_widget = QWidget(self.mainWidget)
        self.endpoint_layout = QFormLayout()

        self.endpoint = QLineEdit(self.endpoint_widget)
        self.endpoint.setPlaceholderText("GPU Endpoint")
        self.endpoint.setText("http://127.0.0.1:7860/api/predict")

        self.endpoint_layout.addRow("Endpoint", self.endpoint)
        self.endpoint_widget.setLayout(self.endpoint_layout)
        self.mainWidget.layout().addWidget(self.endpoint_widget)
        
        self.status = QLabel('Status')
        self.endpoint_layout.addRow(self.status)

        # Dream button ===
        self.dream = QPushButton(self.mainWidget)
        self.dream.setText("Dream")
        self.dream.clicked.connect(self.pingServer)
        

        self.mainWidget.layout().addWidget(self.dream)
        

    def canvasChanged(self, canvas):
        """
        This function must exists per Krita documentation.
        """
        pass

    def generateRequest(self, image_base64, width, height):
        """
        Take all input from user and construct a mapping object.

        Return: Encoded bytes to send as data in post request.
        """
        prompt = str(self.prompt.text())
        steps = str(self.steps.value())
        sketch_strength = str(1.0-self.sketch_strengh.value())
        seed = str(self.seed.text().strip())
        prompt_strength = str(self.prompt_strength.value())
               
        req = f"""{{"fn_index": 0, "data":["data:image/jpeg;base64,{image_base64}","{prompt}",{sketch_strength},\
            {steps},1,1,{height},{width},{prompt_strength},0,1,"cuda","{seed}","outputs/img2img-samples",\
            "png",false,false],"session_hash": "939c4jg2bnk"}}"""
        
        return req

    def get_endpoint(self):
        return str(self.endpoint.text())

    def get_next_layer_id(self):
        self.ITER += 1
        return f"dream_{self.ITER}"

    def pingServer(self):
        
        self.showInfoMessage('Generating image ...')

        # get the current layer as a I/O buffer
        try:
            image_buffer, width, height  = self.layer2buffer()
        except BaseException as e:
            self.showerrorMessage(e)
            return
        
        image_encodedStr = encoded = base64.b64encode(image_buffer.getvalue()).decode("UTF-8")

        data = self.generateRequest(image_encodedStr, width, height)
        header = {"Content-Type": "application/json"}
        
        try: 
            responseJson = self.post(self.get_endpoint(),data)
        except requests.exceptions.RequestException as e:
            self.showerrorMessage(e)
            return
        
        image_data=responseJson["data"][0].replace('data:image/png;base64,', '')
        responseSeed = responseJson["data"][1].rsplit('=', 1)[1]
        self.seed.setText(responseSeed)
        returned_image = QImage.fromData(base64.b64decode(image_data))

        # create a new layer and add it to the document
        application = Krita.instance()
        doc = application.activeDocument()
        root = doc.rootNode()
        dream_layer = doc.createNode(self.get_next_layer_id(), "paintLayer")
        root.addChildNode(dream_layer, None)

        # get a pointer to the image's bits and add them to the new layer
        ptr = returned_image.bits()
        ptr.setsize(returned_image.byteCount())
        dream_layer.setPixelData(
            QByteArray(ptr.asstring()),
            0,
            0,
            returned_image.width(),
            returned_image.height(),
        )
        
        self.showSuccessMessage('Done')
        # update user
        doc.refreshProjection()
        return

    def layer2buffer(self):
        """
        Turns the current active layer into a I/O Buffer so that it can be sent over HTTP.
        """
        # get current document
        currentDocument = Krita.instance().activeDocument()
        width, height = (currentDocument.width(), currentDocument.height())
        
        if (width % 64 != 0):
            raise BaseException('Document width error, must be multiple of 64')
        
        if (height % 64 != 0):
            raise BaseException('Document height error, must be multiple of 64')

        # get current layer
        currentLayer = currentDocument.activeNode()

        # get the pixel data
        pixelData = currentLayer.pixelData(0, 0, width, height)

        # construct QImage
        qImage = QImage(pixelData, width, height, QImage.Format_RGBA8888)
        qImage = qImage.rgbSwapped()

        # now make a buffer and save the image into it
        buffer = QBuffer()
        buffer.open(QIODevice.ReadWrite)
        qImage.save(buffer, format="JPEG")

        # write the data into a buffer and jump to start of file
        image_byte_buffer = BytesIO()
        image_byte_buffer.write(buffer.data())
        image_byte_buffer.read()
        buffer.close()
        image_byte_buffer.seek(0)

        return image_byte_buffer, width, height

    def showInfoMessage(self,message):
        label = f'<p style="color:blue">{message}</p>'
        self.status.setText(label)
        
    def showSuccessMessage(self,message):
        label = f'<p style="color:green">{message}</p>'
        self.status.setText(label)
    
    def showerrorMessage(self,message):
        label = f'<p style="color:red">{message}</p>'
        self.status.setText(label)
    
    def post(self, url, body):
        req = request.Request(url)
        req.add_header('Content-Type', 'application/json')
        body_encoded = body.encode('utf-8')
        req.add_header('Content-Length', str(len(body_encoded)))
        with request.urlopen(req, body_encoded ) as res:
            return json.loads(res.read())
        