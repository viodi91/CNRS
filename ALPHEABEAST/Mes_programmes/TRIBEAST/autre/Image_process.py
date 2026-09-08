import numpy as np
import cv2
import os
from PIL import Image
class image_processor:
    """
    👁 A class to work with images, modify them, compare them, and more
    """
    def __init__(self, img_adr):
        self.img_adr = img_adr
        self.img_name = os.path.basename(img_adr)
        self.img_repo = os.path.dirname(img_adr)
        self.img = cv2.imread(self.img_adr, cv2.IMREAD_UNCHANGED)
        self.img_rgb = cv2.imread(self.img_adr, cv2.IMREAD_COLOR)
        self.img_gray = cv2.cvtColor(self.img_rgb, cv2.COLOR_BGR2GRAY)
        self.img_height = self.img_gray.shape[0]
        self.img_width = self.img_gray.shape[1]
        self.blue = self.img_rgb[:, :, 0]
        self.green = self.img_rgb[:, :, 1]
        self.red = self.img_rgb[:, :, 2]

        self.img_hsv = cv2.cvtColor(self.img_rgb, cv2.COLOR_BGR2HSV)
        self.hue = self.img_hsv[:, :, 0]
        self.saturation = self.img_hsv[:, :, 1]
        self.value = self.img_hsv[:, :, 2]


    def __str__(self):
        return f"{self.img_name} | height: {self.img_height} | width: {self.img_width} |"

    def __repr__(self):
        return f"{self.img_name} | height: {self.img_height} | width: {self.img_width} |" \
               f"\n located at: \n {self.img_repo}"

    def compare_with(self, ref_img, tolerance=None) -> bool:
        """
        👁 A method to compare 2 images with a degree of accepted tolerance
        ✅ ref_img: the reference image
        ✅ tolerance: the accepted tolerance to compare 2 images
        🔎 if tolerance is not given, comparison should be pixel by pixel
        ↩ Returns True if images are similar, otherwise False
        """
        pass

    def find_img_in_grey(self, reference_img, tolerance: float) -> list:
        """
        👁 A method to find the instance image inside the reference image
        ✅ reference_img: the reference image in color or grayscale
        ✅ tolerance: the accepted similarity tolerance for detection
        ✅ output_path: path to save the annotated image
        ↩ Returns a list of dictionaries containing the X, Y, height, width of the found pieces
            👓 example:
        """
        output_path =("C:\\PROJECT\\SOFTWARE\\Iso_MergerKNA_G2\\Python_IsoMergerKNA_G2_Testing_Tool\\Python_bench_data"
                      "\\Python_project\\output\\image_found\\output_image_gray.PNG")

        ############################### Ensure_reference_img_is_grayscale ##############################################
        if len(reference_img.shape) == 3 and reference_img.shape[2] == 3:  # Check if it's a color image
            reference_img_gray = cv2.cvtColor(reference_img, cv2.COLOR_BGR2GRAY)


        else:
            reference_img_gray = reference_img

        ############################### Check_if_template_img_can_be_found_in_reference_img ############################
        result = cv2.matchTemplate(reference_img_gray, self.img_gray, cv2.TM_CCOEFF_NORMED)



        ################ Register_the_x,y_coords_where_the_tolerance_coefficient_is_respected ##########################
        loc = np.where(result >= tolerance)

        ############################### If_nothing_matches_the_tolerance_return_empty_list #############################
        if len(loc[0]) == 0:
            return []

        #################################### Create_a_list_of_dictionaries_for_all_matches #############################
        found_images = [{"X": int(pt[0]), "Y": int(pt[1]), "width": self.img_width, "height": self.img_height}
                        for pt in zip(*loc[::-1])]

        ########################### Annotate_the_reference_image_with_green_rectangles #################################
        if len(reference_img.shape) == 2:  # If grayscale
            reference_img_color = cv2.cvtColor(reference_img, cv2.COLOR_GRAY2BGR)
        else:
            reference_img_color = reference_img.copy()

        ################################ Draw green rectangles around detected areas ###################################
        for item in found_images:
            top_left = (item["X"], item["Y"])
            bottom_right = (item["X"] + item["width"], item["Y"] + item["height"])
            cv2.rectangle(reference_img_color, top_left, bottom_right, (0, 255, 0), 2)  # Green color, thickness=2

        ############################ Save_the_annotated_image ##########################################################
        cv2.imwrite(output_path, reference_img_color)
        return found_images

    def find_img_in_color_HSV(self, reference_img, tolerance: float) -> list:
        """
        👁 A method to find the template image inside the reference image in color using HSV color space.
        ✅ reference_img: the reference image in color or grayscale
        ✅ tolerance: the accepted similarity tolerance for detection
        ↩ Returns a list of dictionaries containing the X, Y, height, width of the found pieces
        """
        output_path = "C:\\PROJECT\\SOFTWARE\\Iso_MergerKNA_G2\\Python_IsoMergerKNA_G2_Testing_Tool\\Python_bench_data" \
                      "\\Python_project\\output\\image_found\\output_image_color.PNG"

        # Ensure the reference image is in color
        if len(reference_img.shape) != 3 or reference_img.shape[2] != 3:
            return []
        elif len(self.img_rgb.shape) != 3 or self.img_rgb.shape[2] != 3:
            return []

        # Convert the reference image to HSV
        reference_img_hsv = cv2.cvtColor(reference_img, cv2.COLOR_BGR2HSV)

        ############################### Check_if_template_img_can_be_found_in_reference_img using HSV ##################
        result_h = cv2.matchTemplate(reference_img_hsv[:, :, 0], self.hue, cv2.TM_CCOEFF_NORMED)
        result_s = cv2.matchTemplate(reference_img_hsv[:, :, 1], self.saturation, cv2.TM_CCOEFF_NORMED)
        result_v = cv2.matchTemplate(reference_img_hsv[:, :, 2], self.value, cv2.TM_CCOEFF_NORMED)

        ################ Register_the_x,y_coords_where_the_tolerance_coefficient_is_respected ##########################
        loc_h = result_h >= tolerance
        loc_s = result_s >= tolerance
        loc_v = result_v >= tolerance

        loc = np.where(loc_h & loc_s & loc_v)

        #################################### Create_a_list_of_dictionaries_for_all_matches #############################
        found_images = [{"X": int(pt[0]), "Y": int(pt[1]), "width": self.img_width, "height": self.img_height}
                        for pt in zip(*loc[::-1])]

        ################################ Draw green rectangles around detected areas ###################################
        for item in found_images:
            top_left = (item["X"], item["Y"])
            bottom_right = (item["X"] + self.img_width, item["Y"] + self.img_height)
            cv2.rectangle(reference_img, top_left, bottom_right, (0, 255, 0), 2)  # Green color, thickness=2

        ############################ Save_the_annotated_image ##########################################################
        cv2.imwrite(output_path, reference_img)

        return found_images

    def find_img_with_transparency(self, reference_img, tolerance: float) -> list:
        """
        👁 A method to find the template image with transparency inside the reference image.
        ✅ reference_img: the reference image in color or grayscale
        ✅ tolerance: the accepted similarity tolerance for detection
        ↩ Returns a list of dictionaries containing the X, Y, height, width of the found pieces.
        """

        ###########################Load the template with transparency (assuming RGBA)##################################
        if self.has_transparency():
            alpha_channel = self.img[:, :, 3]
            _, mask = cv2.threshold(alpha_channel, 1, 255, cv2.THRESH_BINARY)
            # Remove the transparent background by setting the transparent regions to black
            template_rgb = cv2.bitwise_and(self.img[:, :, :3], self.img[:, :, :3], mask=mask)

        else:
            raise ValueError("Template image does not have a transparent background (no alpha channel).")

        ###################################Ensure the reference image is in color#######################################
        if len(reference_img.shape) == 2:  # Grayscale to color
            reference_img_color = cv2.cvtColor(reference_img, cv2.COLOR_GRAY2BGR)
        else:
            reference_img_color = reference_img

        ###################################Perform template matching ignoring the transparent areas#####################
        result = cv2.matchTemplate(reference_img_color, template_rgb, cv2.TM_CCOEFF_NORMED, mask=mask)

        ###################################Find where the template matches with a sufficient tolerance##################
        loc = np.where(result >= tolerance)

        ###################################If no matches are found, return an empty list################################
        if len(loc[0]) == 0:
            return []

        ###################################Create a list of dictionaries with the found coordinates#####################
        found_images = [
            {"X": int(pt[0]), "Y": int(pt[1]), "width": template_rgb.shape[1], "height": template_rgb.shape[0]}
            for pt in zip(*loc[::-1])]

        ##########################Annotate the reference image with green rectangles around the found areas#############
        for item in found_images:
            top_left = (item["X"], item["Y"])
            bottom_right = (item["X"] + item["width"], item["Y"] + item["height"])
            cv2.rectangle(reference_img_color, top_left, bottom_right, (0, 255, 0), 2)  # Green color, thickness=2

        ###################Save the annotated image (you can modify the output path as needed)##########################
        output_path = "C:\\PROJECT\\SOFTWARE\\Iso_MergerKNA_G2\\Python_IsoMergerKNA_G2_Testing_Tool\\Python_bench_data" \
                      "\\Python_project\\output\\image_found\\output_image_with_transparency.PNG"
        cv2.imwrite(output_path, reference_img_color)

        return found_images

    def has_transparency(self):
        """
       👁 A method to check if an image has transparent pixels
       ↩ Returns True if a transparent pixel has be found otherwise if returns False.
        """
        if self.img.shape[2] == 4:  # Vérifier si l'image a un canal alpha
            alpha_channel = self.img[:, :, 3]
            return np.any(alpha_channel < 255)
        return False
