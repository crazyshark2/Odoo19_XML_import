# -*- coding: utf-8 -*-

from odoo import models, fields


class ProductTemplateImageMixin(models.Model):
    _inherit = 'product.template'

    mobilsoft_image_ids = fields.One2many(
        'mobilsoft.product.image', 'product_tmpl_id',
        string='Extra Images (mobilsoft)',
    )

    def _get_images(self):
        try:
            images = super()._get_images()
        except Exception:
            images = [self]
        try:
            images.extend(list(self.mobilsoft_image_ids))
        except Exception:
            pass
        return images


class ProductProductImageMixin(models.Model):
    _inherit = 'product.product'

    def _get_images(self):
        try:
            images = super()._get_images()
        except Exception:
            images = [self]
        try:
            images.extend(list(self.product_tmpl_id.mobilsoft_image_ids))
        except Exception:
            pass
        return images
