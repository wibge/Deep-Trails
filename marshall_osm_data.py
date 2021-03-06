import numpy as np
'''
    1) download geojson road tiles from mapzen
    2) convert the road geographic linestrings to pixels
    2a) rasterize the roads to pixel matrices for the tiles
    2b) try using 2 pixels for the road width, then fix this with trial/error
    3b) further fix with a training layer to guess come up with the width predicitvely
    3) download corresponding MapQuest imagery for the tiles
    4) train a deep learning net with the roads as labeled data for the imagery
    5) 

    geo help from: https://gist.github.com/tucotuco/1193577


'''

import os, math, urllib, sys, json
from globalmaptiles import GlobalMercator
import pyclipper

MAPZEN_VECTOR_TILES_API_KEY = 'vector-tiles-NsMiwBc'

class BoundingBox:
  def __init__(self):
    self.northeast = Coordinate()
    self.southwest = Coordinate()


class Coordinate:
  def __init__(self, lat=-999, lon=-999):
    self.lat = lat
    self.lon = lon

  def __str__(self):
    return "{} {}".format(self.lat, self.lon)


class MercatorTile:
  def __init__(self, x=-1, y=-1, z=-1):
    self.x = x
    self.y = y 
    self.z = z

  def __str__(self):
    return "{} {} {}".format(self.x, self.y, self.z)


class Pixel:
  def __init__(self, x=0, y=0):
    self.x = x
    self.y = y

  def __str__(self):
    return "{} {}".format(self.x, self.y)


class OSMDataNormalizer:  

  def __init__(self):
    data_dir = "data/"
    self.tile_size = 256
    self.make_directory(data_dir)
    self.vector_tiles_dir = "data/vector-tiles/"
    self.make_directory(self.vector_tiles_dir)

    self.current_tile = None

  def make_directory(self, new_dir):
    '''
       make a directory or complain it already exists
    '''
    try:
      os.mkdir(new_dir);
    except:
      pass
      #print("{} already exists".format(new_dir))

  def tile_with_coordinates_and_zoom(self, coordinates, zoom):
    scale = (1<<zoom);
    normalized_point = self.normalize_pixel_coords(coordinates)
    return MercatorTile(int(normalized_point.lat * scale), 
                        int(normalized_point.lon * scale), 
                        int(zoom)
                       )

  def normalize_pixel_coords(self, coord):
    if coord.lon > 180:
      coord.lon -= 360
    coord.lon /= 360.0
    coord.lon += 0.5
    coord.lat = 0.5 - ((math.log(math.tan((math.pi/4) + ((0.5 * math.pi *coord.lat) / 180.0))) / math.pi) / 2.0)
    return coord    

  def tiles_for_bounding_box(self, bounding_box, zoom):
    tile_array = []
    ne_tile = self.tile_with_coordinates_and_zoom(bounding_box.northeast,
                                                  zoom)
    sw_tile = self.tile_with_coordinates_and_zoom(bounding_box.southwest,
                                                  zoom)
      
    min_x = min(ne_tile.x, sw_tile.x)
    min_y = min(ne_tile.y, sw_tile.y)
    max_y = max(ne_tile.y, sw_tile.y)
    max_x = max(ne_tile.x, sw_tile.x)
    for y in range(min_y, max_y):
      for x in range(min_x, max_x):
        new_tile = MercatorTile()
        new_tile.x = x
        new_tile.y = y
        new_tile.z = zoom
        tile_array.append(new_tile)
    return tile_array

  def download_tile(self, tile):
      url = self.url_for_tile(tile)
      z_dir = self.vector_tiles_dir + str(tile.z)
      y_dir = z_dir + "/" + str(tile.y)
      self.make_directory(z_dir)
      self.make_directory(y_dir)
      format = 'json'
      filename = '{}.{}'.format(tile.x,format)
      download_path = y_dir + "/" + filename
      urllib.urlretrieve (url, download_path)

  def url_for_tile(self, tile, base_url='http://vector.mapzen.com/osm/'):
      layers = 'roads'
      format = 'json'
      api_key = MAPZEN_VECTOR_TILES_API_KEY
      filename = '{}.{}'.format(tile.x,format)
      url = base_url + '{}/{}/{}/{}?api_key={}'.format(layers,tile.z,tile.y,filename,api_key)
      return url 

  def osm_url_for_tile(self, tile):
      base_url='http://b.tile.thunderforest.com/outdoors/'
      filename = '{}.{}'.format(tile.x,'png')
      url = base_url + '{}/{}/{}'.format(tile.z,tile.y,filename)
      return url 

  def download_geojson(self):
    ''' 
        download geojson tiles for Yosemite Village from mapzen
    '''
    yosemite_village_bb = BoundingBox()
    yosemite_village_bb.northeast.lat = 37.81385
    yosemite_village_bb.northeast.lon = -119.48559
    yosemite_village_bb.southwest.lat = 37.66724
    yosemite_village_bb.southwest.lon = -119.72454
    zoom = 12

    for tile in self.tiles_for_bounding_box(yosemite_village_bb, zoom):
      self.download_tile(tile)

  def process_geojson(self):
    rootdir = self.vector_tiles_dir
    self.gm = GlobalMercator()
    for folder, subs, files in os.walk(rootdir):
      for filename in files:
        #if os.path.join(folder, filename) != 'data/vector-tiles/12/685/1583.json':
        #  continue
        with open(os.path.join(folder, filename), 'r') as src:
          linestrings = self.linestrings_for_tile(src)
        tile_matrix = self.empty_tile_matrix()
        tile = self.tile_for_folder_and_filename(folder, filename)
        self.current_tile = tile
        print "\nAdding lines for: " + self.osm_url_for_tile(tile)
        # SWNE
        tile_bounds = self.gm.GoogleTileLatLonBounds(tile.y, tile.x, tile.z)
        # WSEN
        tile_bounds = (tile_bounds[1],tile_bounds[0],tile_bounds[3],tile_bounds[2])
        new_bounds = self.clip_tile_bounds(tile_bounds)
        print "\nnew bounds clipping to {}\n".format(new_bounds)
        clipped_linestrings = self.clipped_linestrings(tile.z, new_bounds, linestrings)
        print clipped_linestrings
        #for linestring in clipped_linestrings:
        for linestring in linestrings:
          tile_matrix = self.add_linestring_to_matrix(linestring, tile, tile_matrix)
        self.print_matrix(tile_matrix)

  def clip_tile_bounds(self,bounds):
    new_bounds = []
    for point in bounds:
      if point > 0:
        new_bounds.append((int(point*100000))/100000.0 )
      else:
        new_bounds.append((int(point*100000))/100000.0 )
    return new_bounds

  def tile_for_folder_and_filename(self, folder, filename):
    dir_string = folder.split(self.vector_tiles_dir)
    z, x = dir_string[1].split('/')
    y = filename.split('.')[0]
    return MercatorTile(int(x), int(y), int(z))

  def linestrings_for_tile(self, file_data):
    features = json.loads(file_data.read())['features']
    linestrings = []          
    count = 0
    for f in features:
      if f['geometry']['type'] == 'LineString':
        linestring = f['geometry']['coordinates']
        linestrings.append(linestring)   
      if f['geometry']['type'] == 'MultiLineString':
        for ls in f['geometry']['coordinates']:
          linestrings.append(ls)   
    return linestrings

  def clipped_linestrings(self, zoom, bounding_box, linestrings):
    point_count = 0
    for l in linestrings:
      for p in l:
        point_count += 1
    print "clipping {} points".format(point_count)
    scaling_factor = pow(10, self.decimal_places_for_zoom(zoom))
    clip_box = (
        (int(bounding_box[0] * scaling_factor), int(bounding_box[1] * scaling_factor)),
        (int(bounding_box[2] * scaling_factor), int(bounding_box[1] * scaling_factor)),
        (int(bounding_box[2] * scaling_factor), int(bounding_box[3] * scaling_factor)),
        (int(bounding_box[0] * scaling_factor), int(bounding_box[3] * scaling_factor)),
        (int(bounding_box[0] * scaling_factor), int(bounding_box[1] * scaling_factor)),
    )
    scaled_coordinates = [[(int(c[0] * scaling_factor),
              int(c[1] * scaling_factor)) for c in linestring] \
          for linestring in linestrings]
    pc = pyclipper.Pyclipper()
    pc.AddPath(clip_box, pyclipper.PT_CLIP, True)
     
    try:
      pc.AddPaths(scaled_coordinates, pyclipper.PT_SUBJECT, False)
      solution = pc.Execute2(pyclipper.CT_INTERSECTION, pyclipper.PFT_EVENODD, pyclipper.PFT_EVENODD)
      solution_paths = pyclipper.OpenPathsFromPolyTree(solution)
      unscaled_coordinates = [[(c[0]*1.0 / scaling_factor, c[1]*1.0 / scaling_factor) \
          for c in linestring] for linestring in solution_paths]
      linestrings = unscaled_coordinates
      print "clipped to {}".format(linestrings)
    except Exception, e:
      print("error clipping track")
    point_count = 0
    for l in linestrings:
      for p in l:
        point_count += 1
    print "clipped to {} points".format(point_count)

    return linestrings

  def decimal_places_for_zoom(self, z):
    if z <= 1:
        return 1
    elif z <= 4:
        return 2
    elif z <= 7:
        return 3
    elif z <= 10:
        return 4
    elif z <= 13:
        return 5
    else:
        return 6

  def add_linestring_to_matrix(self, linestring, tile, matrix):
    line_matrix = self.pixel_matrix_for_linestring(linestring, tile)
    for x in range(0,self.tile_size):
      for y in range(0,self.tile_size):
        if line_matrix[x][y]:
          matrix[x][y] = line_matrix[x][y] 
    return matrix

  def print_matrix(self, matrix):
    for row in np.rot90(np.fliplr(matrix)):
      row_str = ''
      for cell in row:
        row_str += str(cell)
      print row_str

  def empty_tile_matrix(self):
    # initialize the array to all zeroes
    tile_matrix = []    
    for x in range(0,self.tile_size):
      tile_matrix.append([])
      for y in range(0,self.tile_size):
        tile_matrix[x].append(0)     
    return tile_matrix

  def pixel_matrix_for_linestring(self, linestring, tile):
    '''
       set pixel_matrix to 1 for every point between all points on the line string
    '''

    line_matrix = self.empty_tile_matrix()
    zoom = tile.z

    count = 0
    for current_point in linestring:
      if count == len(linestring) - 1:
        break
      next_point = linestring[count+1]
      current_point_obj = Coordinate(current_point[1], current_point[0])
      next_point_obj = Coordinate(next_point[1], next_point[0])
      
      start_pixel = self.fromLatLngToPoint(current_point_obj.lat,
                                      current_point_obj.lon, zoom)      
      end_pixel = self.fromLatLngToPoint(next_point_obj.lat,
                                    next_point_obj.lon, zoom)
      pixels = self.pixels_between(start_pixel, end_pixel)
      if len(pixels) > 200:
        print "\n****Got a runner boys..." + str(len(pixels))
        
        bounds = self.gm.GoogleTileLatLonBounds(tile.x, tile.y, tile.z)
        #new_bounds = self.clip_tile_bounds(bounds)
        new_bounds = bounds
        print "tile bounds is {}".format(new_bounds)

        if start_pixel.x == 0 or start_pixel.y == 0:
          self.fromLatLngToPoint(current_point_obj.lat,
                                      current_point_obj.lon, zoom, debug=True) 
        if end_pixel.x == 0 or end_pixel.y == 0:
          print "is this point outside of bounds?: {} {}".format(next_point_obj.lat, next_point_obj.lon)
          self.fromLatLngToPoint(next_point_obj.lat,
                                      next_point_obj.lon, zoom, debug=True) 
      for p in pixels:
        line_matrix[p.x][p.y] = 1
      count += 1

    return line_matrix

  def degreesToRadians(self, deg): 
    return deg * (math.pi / 180)
    
  def bound(self, val, valMin, valMax):
    res = 0
    res = max(val, valMin);
    res = min(val, valMax);
    return res;
    
  # TODO - sometimes this function return a bad x or y value.... 
  # we expect it to be 255, but instead its 0, and causes lines to wrap on ascii tiles  
  def fromLatLngToPoint(self, lat, lng, zoom, debug=False):
  
    tile = self.gm.GoogleTileFromLatLng(lat, lng, zoom)
    
    tile_x_offset =  (tile[0] - self.current_tile.x) * self.tile_size
    tile_y_offset = (tile[1] - self.current_tile.y) * self.tile_size
    
    if debug: 
      print "Tile offsets " + str(tile_x_offset) + " " + str(tile_y_offset)
    if debug: print "conversion for these coords may be off tile bounds: {}, {} (z: {})".format(lat, lng, zoom)
    # http://stackoverflow.com/a/17419232/108512
    _pixelOrigin = Pixel()
    _pixelOrigin.x = self.tile_size / 2.0
    _pixelOrigin.y = self.tile_size / 2.0
    _pixelsPerLonDegree = self.tile_size / 360.0
    _pixelsPerLonRadian = self.tile_size / (2 * math.pi)

    point = Pixel()
    point.x = _pixelOrigin.x + lng * _pixelsPerLonDegree
    if debug: print "point.x is {}".format(point.x)

    # Truncating to 0.9999 effectively limits latitude to 89.189. This is
    # about a third of a tile past the edge of the world tile.
    siny = self.bound(math.sin(self.degreesToRadians(lat)), -0.9999,0.9999)
    if debug: print "siny is {}".format(siny)
    point.y = _pixelOrigin.y + 0.5 * math.log((1 + siny) / (1 - siny)) *- _pixelsPerLonRadian
    if debug: print "point.y is {}".format(point.y)

    num_tiles = 1 << zoom
    if debug: print "num_tiles is {}".format(num_tiles)
    if debug: print "values before (Pxy * num_tiles % 256) are {}, {}".format(point.x, point.y)
    if debug: print "Pxy * num_tiles are {}, {}".format(point.x * num_tiles, point.y * num_tiles)
    point.x = int(point.x * num_tiles)%self.tile_size + tile_x_offset
    point.y = int(point.y * num_tiles)%self.tile_size + tile_y_offset
    if debug: print "possibly faulty conversion to {}, {}\n".format(point.x, point.y)
    return point

  def pixel_is_valid(self, p):
    if (p.x >= 0 and p.x < self.tile_size and p.y >= 0 and p.y < self.tile_size):
      return True
    return False


  def pixels_between(self, start_pixel, end_pixel):
    pixels = []
    if end_pixel.x - start_pixel.x == 0:
      for y in range(min(end_pixel.y, start_pixel.y),
                     max(end_pixel.y, start_pixel.y)):
        p = Pixel()
        p.x = end_pixel.x
        p.y = y
        if self.pixel_is_valid(p):
          pixels.append(p) 
      return pixels
      
    slope = (end_pixel.y - start_pixel.y)/float(end_pixel.x - start_pixel.x)
    offset = end_pixel.y - slope*end_pixel.x

    num_points = self.tile_size
    i = 0
    while i < num_points:
      p = Pixel()
      floatx = start_pixel.x + (end_pixel.x - start_pixel.x) * i / float(num_points)
      p.x = int(floatx)
      p.y = int(offset + slope * floatx)
      i += 1
    
      if self.pixel_is_valid(p):
        pixels.append(p) 

    return pixels

odn = OSMDataNormalizer()
#odn.download_geojson()
odn.process_geojson()