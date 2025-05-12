from typing import Any, Optional
from qgis.core import (
    QgsFeature,
    QgsField,
    QgsProcessing,
    QgsProcessingAlgorithm,
    QgsProcessingContext,
    QgsProcessingFeedback,
    QgsProcessingParameterRasterLayer,
    QgsProcessingParameterVectorDestination,
    QgsFeatureSink,
)
from qgis.PyQt.QtCore import QVariant
from qgis import processing
import os

class WaterObjectClassification(QgsProcessingAlgorithm):
    INPUT = "INPUT"
    OUTPUT = "OUTPUT"

    def name(self) -> str:
        return "water_object_classification"

    def displayName(self) -> str:
        return " Классификация водных объектов (озеро, река и т.д.)"

    def group(self) -> str:
        return "Water Analysis"

    def groupId(self) -> str:
        return "wateranalysis"

    def shortHelpString(self) -> str:
        return (
            " Классифицирует водные объекты (озеро, река, ерик и др.) на основе бинарной маски. "
            " Векторизует объекты, рассчитывает площадь, периметр, вытянутость, длину главной оси (через MBR), "
            " присваивает класс каждому объекту."
        )

    def initAlgorithm(self, config: Optional[dict[str, Any]] = None):
        self.addParameter(
            QgsProcessingParameterRasterLayer(
                self.INPUT,
                " Бинарная маска воды (1 - вода, 0 - фон)"
            )
        )
        self.addParameter(
            QgsProcessingParameterVectorDestination(
                self.OUTPUT,
                " Классифицированные водные объекты"
            )
        )

    def processAlgorithm(
        self,
        parameters: dict[str, Any],
        context: QgsProcessingContext,
        feedback: QgsProcessingFeedback,
    ) -> dict[str, Any]:
        mask_layer = self.parameterAsRasterLayer(parameters, self.INPUT, context)
        output_path = self.parameterAsOutputLayer(parameters, self.OUTPUT, context)

        # Удаляем файл, если он существует, чтобы избежать ошибки записи
        if os.path.exists(output_path):
            os.remove(output_path)

        # 1. Векторизация маски
        feedback.pushInfo("Векторизация маски...")
        vectorized = processing.run(
            "gdal:polygonize",
            {
                "INPUT": mask_layer.source(),
                "BAND": 1,
                "FIELD": "DN",
                "EIGHT_CONNECTEDNESS": False,
                "OUTPUT": "TEMPORARY_OUTPUT"
            },
            context=context,
            feedback=feedback
        )["OUTPUT"]

        # 2. Оставляем только объекты воды (DN==1)
        feedback.pushInfo(" Фильтрация водных объектов...")
        only_water = processing.run(
            "native:extractbyattribute",
            {
                "INPUT": vectorized,
                "FIELD": "DN",
                "OPERATOR": 0,  # =
                "VALUE": 1,
                "OUTPUT": "TEMPORARY_OUTPUT"
            },
            context=context,
            feedback=feedback
        )["OUTPUT"]

        # 3. Классификация по площади, вытянутости и длине главной оси (через MBR)
        feedback.pushInfo(" Расчёт геометрических характеристик и классификация...")
        fields = only_water.fields()
        fields.append(QgsField("area_m2", QVariant.Double))
        fields.append(QgsField("perimeter_m", QVariant.Double))
        fields.append(QgsField("elongation", QVariant.Double))
        fields.append(QgsField("main_axis", QVariant.Double))
        fields.append(QgsField("class", QVariant.String))

        (sink, dest_id) = self.parameterAsSink(
            parameters, self.OUTPUT, context, fields, only_water.wkbType(), only_water.sourceCrs()
        )

        total = only_water.featureCount()
        for i, f in enumerate(only_water.getFeatures()):
            if feedback.isCanceled():
                break
            geom = f.geometry()
            area = geom.area()
            perim = geom.length()
            # Вытянутость и главная ось через orientedMinimumBoundingBox
            min_rect_tuple = geom.orientedMinimumBoundingBox()
            if min_rect_tuple is not None:
                min_rect_geom = min_rect_tuple[0]
                if min_rect_geom.isGeosValid():
                    rect_coords = min_rect_geom.asPolygon()[0]
                    side_lengths = [rect_coords[i].distance(rect_coords[i+1]) for i in range(4)]
                    width = min(side_lengths)
                    height = max(side_lengths)
                    elongation = height / width if width > 0 else 1.0
                    main_axis = max(side_lengths)
                else:
                    elongation = 1.0
                    main_axis = 0
            else:
                elongation = 1.0
                main_axis = 0

            # Классификация по нескольким признакам
            if main_axis > 8000 and elongation > 3:
                cls = " Река"
            elif area > 500000 and elongation < 2:
                cls = " Озеро"
            elif area < 20000 and elongation > 2:
                cls = " Ерик"
            elif area < 10000:
                cls = " Пруд"
            else:
                cls = " Водоём"

            new_f = QgsFeature(fields)
            new_f.setGeometry(geom)
            attrs = f.attributes() + [area, perim, elongation, main_axis, cls]
            new_f.setAttributes(attrs)
            sink.addFeature(new_f, QgsFeatureSink.FastInsert)
            feedback.setProgress(int(100 * i / total))

        feedback.pushInfo(" Готово! Классификация завершена.")
        return {self.OUTPUT: dest_id}

    def createInstance(self):
        return WaterObjectClassification()
