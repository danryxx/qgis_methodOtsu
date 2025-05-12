from qgis.core import (
    QgsProcessing,
    QgsProcessingAlgorithm,
    QgsProcessingParameterRasterLayer,
    QgsProcessingParameterRasterDestination
)
import numpy as np
import cv2

class OtsuWaterMask(QgsProcessingAlgorithm):
    INPUT = "INPUT"
    OUTPUT = "OUTPUT"

    def initAlgorithm(self, config=None):
        self.addParameter(
            QgsProcessingParameterRasterLayer(
                self.INPUT,
                " Входной индексный растр (например, NDWI, MNDWI)"
            )
        )
        self.addParameter(
            QgsProcessingParameterRasterDestination(
                self.OUTPUT,
                " Выходная бинарная водная маска"
            )
        )

    def processAlgorithm(self, parameters, context, feedback):
        raster_layer = self.parameterAsRasterLayer(parameters, self.INPUT, context)
        input_path = raster_layer.source()
        
        # Читаем данные через GDAL
        from osgeo import gdal, osr
        ds = gdal.Open(input_path)
        band = ds.GetRasterBand(1)
        arr = band.ReadAsArray()
        nodata = band.GetNoDataValue()
        gt = ds.GetGeoTransform()
        proj = ds.GetProjection()
        height, width = arr.shape

        # МАСКА валидных данных
        valid_mask = np.ones_like(arr, dtype=bool)
        if nodata is not None:
            valid_mask = arr != nodata

        arr_valid = arr[valid_mask]
        arr_valid = arr_valid[~np.isnan(arr_valid)]

        # Нормализация для OpenCV
        arr_min = arr_valid.min()
        arr_max = arr_valid.max()
        arr_norm = ((arr_valid - arr_min) / (arr_max - arr_min) * 255).astype(np.uint8)

        # Otsu threshold
        threshold, _ = cv2.threshold(arr_norm, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        otsu_value = arr_min + (threshold / 255.0) * (arr_max - arr_min)
        feedback.pushInfo(f" Порог Отсу: {otsu_value:.4f}")

        # Бинаризация всего массива
        mask = np.zeros_like(arr, dtype=np.uint8)
        mask[arr >= otsu_value] = 1
        if nodata is not None:
            mask[arr == nodata] = 0

        # Сохраняем результат через GDAL
        output_path = self.parameterAsOutputLayer(parameters, self.OUTPUT, context)
        driver = gdal.GetDriverByName('GTiff')
        out_ds = driver.Create(output_path, width, height, 1, gdal.GDT_Byte)
        out_ds.SetGeoTransform(gt)
        out_ds.SetProjection(proj)
        out_band = out_ds.GetRasterBand(1)
        out_band.WriteArray(mask)
        out_band.SetNoDataValue(0)
        out_band.FlushCache()
        out_ds = None

        return {self.OUTPUT: output_path}

    def name(self):
        return "otsu_water_mask"

    def displayName(self):
        return " Водная маска по методу Отсу"

    def group(self):
        return "Raster analysis"

    def groupId(self):
        return "rasteranalysis"

    def shortHelpString(self):
        return (
            " Создает бинарную маску воды из индексного растра (например, NDWI, MNDWI). "
            " с помощью автоматического порогового метода Отсу."
        )

    def createInstance(self):
        return OtsuWaterMask()
