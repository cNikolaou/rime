import os.path

from ruamel.yaml import YAML

class Config:
    """
    Global configuration for RIME using a YAML file.
    """
    def __init__(self, yaml, base_path='./'):
        self.yaml = yaml
        self.base_path = base_path

    @classmethod
    def from_file(cls, filename):
        yaml = YAML(typ='safe')

        with open(filename) as h:
            config = yaml.load(h)
            base_path = os.path.abspath(os.path.dirname(filename))
            return cls(config, base_path)

    def __getitem__(self, key):
        return self.yaml[key]

    def get(self, key, default=None):
        return self.yaml.get(key, default)

    def get_pathname(self, key):
        val = self.yaml
        for keypart in key.split('.'):
            val = val[keypart]

        return os.path.join(self.base_path, val)
