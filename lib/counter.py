class Counter:
  def __init__(self):
    self.count = 0

  def get(self):
    self.count += 1
    return self.count - 1