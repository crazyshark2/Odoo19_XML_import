from odoo import models, fields, api


class SelectPathWizard(models.TransientModel):
    _name = 'select.path.wizard'
    _description = 'XML Yolu Seçme Sihirbazı'

    mapping_id = fields.Many2one('xml.field.mapping', string='Eşleştirme', required=True)
    source_id = fields.Many2one('xml.product.source', string='XML Kaynağı', required=True)
    path_id = fields.Many2one(
        'xml.source.path',
        string='Yol Seç (Dropdown)',
        domain="[('source_id', '=', source_id)]",
        help='Algılanan XML yollarından seçin. İsterseniz aşağıdaki alana elle de yazabilirsiniz.',
    )
    manual_path = fields.Char(
        string='Yol Yaz (Manuel)',
        help='Dropdown\'da yoksa elle yol adını yazın.',
    )

    def action_confirm(self):
        self.ensure_one()
        if self.manual_path:
            self.mapping_id.xml_path = self.manual_path
        elif self.path_id:
            self.mapping_id.xml_path = self.path_id.name
        return {'type': 'ir.actions.act_window_close'}
