# coding=utf-8

#     National Oceanic and Atmospheric Administration
#     Alaskan Fisheries Science Center
#     Resource Assessment and Conservation Engineering
#     Midwater Assessment and Conservation Engineering

#  THIS SOFTWARE AND ITS DOCUMENTATION ARE CONSIDERED TO BE IN THE PUBLIC DOMAIN
#  AND THUS ARE AVAILABLE FOR UNRESTRICTED PUBLIC USE. THEY ARE FURNISHED "AS IS."
#  THE AUTHORS, THE UNITED STATES GOVERNMENT, ITS INSTRUMENTALITIES, OFFICERS,
#  EMPLOYEES, AND AGENTS MAKE NO WARRANTY, EXPRESS OR IMPLIED, AS TO THE USEFULNESS
#  OF THE SOFTWARE AND DOCUMENTATION FOR ANY PURPOSE. THEY ASSUME NO RESPONSIBILITY
#  (1) FOR THE USE OF THE SOFTWARE AND DOCUMENTATION; OR (2) TO PROVIDE TECHNICAL
#  SUPPORT TO USERS.


import os
import datetime
from pytz import timezone
import numpy as np
from .util.raw_file import RawSimradFile, SimradEOF
from ..ping_data import ping_data
from ..processing import processed_data
from ..processing import line
from .util.nmea_data import nmea_data


class EK60(object):
    """Summary of class here.

    Longer class information....
    Longer class information....

    Attributes:
        likes_spam: A boolean indicating if we like SPAM or not.
        eggs: An integer count of the eggs we have laid.
    """


    def __init__(self):

        """Fetches rows from a Bigtable.

            Retrieves rows pertaining to the given keys from the Table instance
            represented by big_table.  Silly things may happen if
            other_silly_variable is not None.

            Args:
                big_table: An open Bigtable Table instance.
                keys: A sequence of strings representing the key of each table row
                    to fetch.
                other_silly_variable: Another optional variable, that has a much
                    longer name than the other args, and which does nothing.

            Returns:
                A dict mapping keys to the corresponding table row data
                fetched. Each row is represented as a tuple of strings. For
                example:

                {'Serak': ('Rigel VII', 'Preparer'),
                 'Zim': ('Irk', 'Invader'),
                 'Lrrr': ('Omicron Persei 8', 'Emperor')}

                If a key from the keys argument is missing from the dictionary,
                then that row was not found in the table.

            Raises:
                IOError: An error occurred accessing the bigtable.Table object.
        """

        #  define the EK60's properties - these are "read-only" properties and should not
        #  be changed directly by the user

        #  start_time and end_time will define the time span of the data within the EK60 class
        self.start_time = None
        self.end_time = None

        #  start_ping and end_ping will define the ping span of the data within the EK60 class
        self.start_ping = None
        self.end_ping = None

        #  n_pings stores the total number of pings read
        self.n_pings = 0

        #  a list of frequencies that have been read.
        self.frequencies = []

        #  a list of stings identifying the channel IDs that have been read
        self.channel_ids = []

        #  channel_id_map maps the channel number to channel ID when reading raw data sources
        self.channel_id_map = {}

        #  n_channels stores the total number of channels in the object
        self.n_channels = 0

        #  create a dictionary to store the RawData objects
        self.raw_data = {}

        #  create a dictionary to store the NMEA object
        self.nmea_data = nmea_data()

        #  Define the class's "private" properties. These should not be generally be directly
        #  manipulated by the user.

        #  specify if we should read files incrementally or all at once
        self.read_incremental = False

        #  define an internal state variable that is set when we initiate incremental reading
        self._is_reading = False

        #  set read_angles to true to store angle data
        self.read_angles = True

        #  set read_angles to true to store power data
        self.read_power = True

        #  specify the max sample count to read. This property can be used to limit the
        #  number of samples read (and memory used) when your data of interest is
        self.read_max_sample_count = None

        #  data_array_dims contains the dimensions of the sample and angle data arrays
        #  specified as [n_pings, n_samples]. Values of -1 specify that the arrays will
        #  be resized appropriately to contain all pings and all samples read from the
        #  data source. Settings values > 0 will create arrays that are fixed to that size.
        #  Any samples beyond the number specified as n_samples will be dropped. When a
        #  ping is added and the data arrays are full, the sample data will be rolled such
        #  that the oldest data is dropped and the new ping is added.
        self._data_array_dims = [-1, -1]

        #  store the time and ping range, and sample range parameters
        self.read_start_time = None
        self.read_end_time = None
        self.read_start_ping = None
        self.read_end_ping = None
        self.read_start_sample = None
        self.read_end_sample = None

        #  read_frequencies can be set to a list of floats specifying the frequencies to
        #  read. An empty list will result in all frequencies being read.
        self.read_frequencies = []

        #  read_channel_ids can be set to a list of strings specifying the channel_ids of
        #  the channels to read. An empty list will result in all channels being read.
        self.read_channel_ids = []

        #  this is the internal per file channel map which maps the channels in the file
        #  to the channels we are reading. This map is only valid for the file
        #  currently being read. Do not alter or use this property.
        self._channel_map = {}

        #  this is yet another channel mapping - this maps channel id's to channel number
        #  and is used to map bottom detections to specific channels. This list differs
        #  from the other lists of ids as it contains all ids in the file, not just the
        #  ones we're storing.
        self._file_channel_map = []


    def read_bot(self, bot_files):
        """
        read_bot passes a list of .bot filenames to read_raw. Because of the
        requriement to read a .bot/.out file after the .raw data it may be
        more convienient to simply call this after reading your .raw files.

        This does potentially provide a small optimization when reading .out
        files in that this method will set the start and end time arguments
        to read_raw based on the start and end times of the raw data so bottom
        detections outside of this range will be skipped immediately after
        reading instead of being checked against the data ping times.

        Note that you don't *have* to call this method to read .bot/.out
        files. You can call read_raw directly but you must read your .raw
        data before reading the .bot file which means the .raw file associated
        with a .bot/.out file must come before said .out/.bot file in the
        list of raw files.
        """
        self.read_raw(bot_files, start_time=self.start_time,
                end_time=self.end_time)


    def read_raw(self, raw_files, power=None, angles=None, max_sample_count=None, start_time=None,
            end_time=None, start_ping=None, end_ping=None, frequencies=None, channel_ids=None,
            time_format_string='%Y-%m-%d %H:%M:%S', incremental=None, start_sample=None,
            end_sample=None):
        """
        read_raw reads one or many Simrad EK60 ES60/70 .raw files. This method
        also reads .out and .bot files but you must read the .raws files
        associated with a .bot or .out file *before* reading the bottom file.
        (.bot files are associted with a single .raw file while .out files
        can be associated with one or more .raw files.)

        """

        #  update the reading state variables
        if (start_time):
            self.read_start_time = self._convert_time_bound(start_time,
                    format_string=time_format_string)
        if (end_time):
            self.read_end_time = self._convert_time_bound(end_time,
                    format_string=time_format_string)
        if (start_ping):
            self.read_start_ping = start_ping
        if (end_ping):
            self.read_end_ping = end_ping
        if (start_sample):
            self.read_start_sample = start_sample
        if (end_sample):
            self.read_end_sample = end_sample
        if (power):
            self.read_power = power
        if (angles):
            self.read_angles = angles
        if (max_sample_count):
            self.read_max_sample_count = max_sample_count
        if (frequencies):
            self.read_frequencies = frequencies
        if (channel_ids):
            self.read_channel_ids = channel_ids
        if (incremental):
            self.read_incremental = incremental

        #TODO:  Implement incremental reading.
        #       This is going to take some re-org since we can't simply iterate thru the list of files.
        #       We need to be able to read a subset of data from a file and if required open the next
        #       file in the list and continue reading the subset.

        #  ensure that the raw_files argument is a list
        if isinstance(raw_files, str):
            raw_files = [raw_files]

        #  initialize a file counter
        n_files = 0

        #  iterate thru our list of .raw files to read
        for filename in raw_files:

            #  Read data from file and add to self.raw_data.
            with RawSimradFile(filename, 'r') as fid:

                #  read the configuration datagrams - the CON0 datagram will come first
                #  and if this is an ME70 .raw file the CON1 datagram will follow.

                #  read the CON0 configuration datagram
                config_datagram = fid.read(1)

                config_datagram['timestamp'] = \
                        np.datetime64(config_datagram['timestamp'], '[ms]')
                if (n_files == 0):
                    self.start_time = config_datagram['timestamp']

                #  create a mapping of channel numbers to channel IDs for all
                #  transceivers in the file.
                self._file_channel_map = [None] * \
                    config_datagram['transceiver_count']
                for idx in config_datagram['transceivers'].keys():
                    self._file_channel_map[idx-1] = \
                        config_datagram['transceivers'][idx]['channel_id']

                #  check if we're reading an ME70 file with a CON1 datagram
                next_datagram = fid.peek()
                if (next_datagram == 'CON1'):
                    #  the next datagram is CON1 - read it
                    CON1_datagram = fid.read(1)
                else:
                    #  next datagram was something else, move along
                    CON1_datagram = None

                #  check if we need to create an raw_data object for this channel
                self._channel_map = {}
                for channel in config_datagram['transceivers']:
                    #  get the channel ID
                    channel_id = config_datagram['transceivers'][channel]['channel_id']

                    #  check if we are reading this channel
                    if ((self.read_channel_ids) and (channel_id not in self.read_channel_ids)):
                        #  there are specific channel IDs specified and this is *NOT* one of them
                        #  so we just move along...
                        continue

                    #  check if we're reading this frequency
                    frequency = config_datagram['transceivers'][channel]['frequency']
                    if ((self.read_frequencies) and (frequency not in self.read_frequencies)):
                        #  there are specific frequencies specified and this is *NOT* one of them
                        #  so we just move along...
                        continue

                    #  check if an raw_data object exists for this channel
                    if channel_id not in self.raw_data:
                        #  no - create it
                        self.raw_data[channel_id] = raw_data(channel_id,
                                store_power=self.read_power, store_angles=self.read_angles,
                                max_sample_number=self.read_max_sample_count)

                        #  and add it to our list of channel_ids
                        self.channel_ids.append(channel_id)

                        #  update our public channel id map
                        self.n_channels += 1
                        self.channel_id_map[self.n_channels] = channel_id

                    #  update the internal mapping of channel number to channel ID used
                    #  when reading the datagrams. This mapping is only valid for the
                    #  current file that is being read.
                    self._channel_map[channel] = channel_id

                    #  create a channel_metadata object to store this channel's
                    #  configuration and rawfile metadata.
                    metadata = channel_metadata(filename,
                                config_datagram['transceivers'][channel],
                                config_datagram['survey_name'],
                                config_datagram['transect_name'],
                                config_datagram['sounder_name'],
                                config_datagram['version'],
                                self.raw_data[channel_id].n_pings,
                                config_datagram['timestamp'],
                                extended_configuration=CON1_datagram)

                    #  update the channel_metadata property of the RawData object
                    self.raw_data[channel_id].current_metadata = metadata

                #  read the rest of the datagrams.
                self._read_datagrams(fid, self.read_incremental)

                #  increment the file read counter
                n_files += 1

        #  trim excess data from arrays after reading
        for channel_id in self.channel_ids:
            self.raw_data[channel_id].trim()
        self.nmea_data.trim()


    def _read_datagrams(self, fid, incremental):
        """
        _read_datagrams is an internal method to read all of the datagrams contained in
        a raw file.
        """

        #TODO: implement incremental reading
        #      The user should be able to specify incremental reading in their call to read_raw.
        #      incremental reading should read in the specified number of "pings", save the reader
        #      state, then return. Subsequent calls would pick up where the reading left off.
        #      As stated above, the exact mechanics need to be worked out since it will not work
        #      as currently implemented.


        #TODO:  figure out what if anything we want to do with these.
        #       Either expose in some useful way or remove.
        num_sample_datagrams = 0
        num_sample_datagrams_skipped = 0
        num_datagrams_parsed = 0
        num_bot_datagrams = 0

        #  while datagrams are available
        while True:
            #  try to read in the next datagram
            try:
                new_datagram = fid.read(1)
            except SimradEOF:
                #  nothing more to read
                break

            #  convert the timestamp to a datetime64 object
            new_datagram['timestamp'] = \
                    np.datetime64(new_datagram['timestamp'], '[ms]')

            #  check if we should store this data based on time bounds
            if self.read_start_time is not None:
                if new_datagram['timestamp'] < self.read_start_time:
                    continue
            if self.read_end_time is not None:
                if new_datagram['timestamp'] > self.read_end_time:
                    continue

            #  increment the number parsed counter
            num_datagrams_parsed += 1

            #  update our end_time property
            if (self.end_time is not None):
                #  we can't assume data will be read in time order
                if (self.end_time < new_datagram['timestamp']):
                    self.end_time = new_datagram['timestamp']
            else:
                self.end_time = new_datagram['timestamp']

            #  process the datagrams by type

            #  RAW datagrams store raw acoustic data for a channel
            if new_datagram['type'].startswith('RAW'):

                #  increment our ping counter
                if (new_datagram['channel'] == 1):
                    self.n_pings += 1

                #  check if we should store this data based on ping bounds
                if self.read_start_ping is not None:
                    if self.n_pings < self.read_start_ping:
                        continue
                if self.read_end_ping is not None:
                    if self.n_pings > self.read_end_ping:
                        continue

                #  check if we're supposed to store this channel
                if new_datagram['channel'] in self._channel_map:

                    #  set the first ping number we read
                    if (not self.start_ping):
                        self.start_ping = self.n_pings
                    #  and update the last ping number
                    self.end_ping = self.n_pings

                    #  get the channel id
                    channel_id = self._channel_map[new_datagram['channel']]

                    #  and call the appropriate channel's append_ping method
                    self.raw_data[channel_id].append_ping(new_datagram,
                            start_sample=self.read_start_sample,
                            end_sample=self.read_end_sample)

                    # increment the sample datagram counter
                    num_sample_datagrams += 1
                else:
                    num_sample_datagrams_skipped += 1

            #  NME datagrams store ancillary data as NMEA-0817 style ASCII data
            elif new_datagram['type'].startswith('NME'):
                #  add the datagram to our nmea_data object
                self.nmea_data.add_datagram(new_datagram['timestamp'],
                        new_datagram['nmea_string'])

            #  TAG datagrams contain time-stamped annotations inserted via the
            #  recording software
            elif new_datagram['type'].startswith('TAG'):
                #TODO: Implement annotation reading
                print(new_datagram)
                pass

            #  BOT datagrams contain sounder detected bottom depths from ".bot" files
            elif new_datagram['type'].startswith('BOT'):
                #  iterate thru our channels, extract the depth,
                #  and update the channel.
                for channel_id in self.channel_ids:
                    idx = self._file_channel_map.index(channel_id)
                    bottom_depth = new_datagram['depth'][idx]
                    #  and call the appropriate channel's append_bot method
                    self.raw_data[channel_id].append_bot(new_datagram['timestamp'],
                            bottom_depth)

                # increment the sample datagram counter
                num_bot_datagrams += 1

            #  DEP datagrams contain sounder detected bottom depths from ".out" files
            #  as well as "reflectivity" data
            elif new_datagram['type'].startswith('DEP'):
                #  iterate thru our channels, extract the depth,
                #  and update the channel.
                for channel_id in self.channel_ids:
                    idx = self._file_channel_map.index(channel_id)
                    bottom_depth = new_datagram['depth'][idx]
                    reflectivity = new_datagram['reflectivity'][idx]
                    #  and call the appropriate channel's append_bot method, including
                    #  reflectivity
                    self.raw_data[channel_id].append_bot(new_datagram['timestamp'],
                            bottom_depth, reflectivity=reflectivity)

                # increment the sample datagram counter
                num_bot_datagrams += 1
            else:
                print("Unknown datagram type: " + str(new_datagram['type']))


    def _convert_time_bound(self, time, format_string):
        """
        internally all times are converted to UTC timezone. This method
        converts arguments to comply.
        """
        #  if we've been given a datetime64[ms] object nothing to convert
        if (time.dtype == '<M8[ms]'):
            return

        utc = timezone('utc')
        if (isinstance(time, str)):
            #  we have been passed a string, convert to datetime object
            time = datetime.datetime.strptime(time, format_string)

        #  make sure our datetime object is converted to UTC
        if (isinstance(time, datetime.datetime)):
            time = utc.localize(time)

        #  and return
        return time


    def get_raw_data(self, channel_number=None, channel_id=None):
        """
        Get the raw data for a specific channel

        get_rawdata returns a reference to the specified raw_data object for
        the specified channel id or channel number. If no channel
        number or id are specified it returns a dictionary keyed by channel
        id containing all of the channels.

        Args:
            channel_number (int): Channel from which to return the raw data
            channel_id (str): The channel ID from which to return the raw data

        Returns: Raw data object from the specified channel
        """

        if (channel_id is not None):
            #  channel id specified
            channel_data = self.raw_data.get(channel_id, None)
        elif (channel_number is not None):
            #  channel number specified
            try:
                channel_data = self.raw_data.get(self.channel_id_map
                                             [channel_number], None)
            except KeyError:
                #  no channel id for this channel number
                channel_data = None
        else:
            #  no channel id or number specified - return all in a
            #  dict keyed by channel ID
            channel_data = self.raw_data

        if channel_data:
            return channel_data
        else:
            raise ValueError('The specified chanel number or channel ID does '
                             'not exists')


    def __str__(self):
        """
        reimplemented string method that provides some basic info about the EK60
        """

        #  print the class and address
        msg = str(self.__class__) + " at " + str(hex(id(self))) + "\n"

        #  print some more info about the EK60 instance
        if (self.channel_ids):
            n_channels = len(self.channel_ids)
            if (n_channels > 1):
                msg = msg + ("    EK60 object contains data from " + str(n_channels) + " channels:\n")
            else:
                msg = msg + ("    EK60 object contains data from 1 channel:\n")
            for channel in self.channel_id_map:
                msg = msg + ("        " + str(channel) + ":" + self.channel_id_map[channel] + "\n")
            msg = msg + ("    data start time: " + str(self.start_time)+ "\n")
            msg = msg + ("      data end time: " + str(self.end_time)+ "\n")
            msg = msg + ("    number of pings: " + str(self.end_ping - self.start_ping + 1)+ "\n")

        else:
            msg = msg + ("  EK60 object contains no data\n")

        return msg


class raw_data(ping_data):
    """
    the raw_data class contains a single channel's data extracted from a Simrad raw
    file. collected from an EK/ES60 or ES70. A raw_data object is created for each
    unique channel in an EK/ES60 ES70 raw file.

    """

    #  define some instrument specific constants

    #  Simrad recommends a TVG correction factor of 2 samples to compensate for receiver delay and TVG
    #  start time delay in EK60 and related hardware. Note that this correction factor is only applied
    #  when computing Sv/sv and not Sp/sp.
    TVG_CORRECTION = 2

    #  define constants used to specify the target resampling interval for the power and angle
    #  conversion functions. These values represent the standard sampling intervals for EK60 hardware
    #  when operated with the ER60 software as well as ES60/70 systems and the ME70(?)
    RESAMPLE_SHORTEST = 0
    RESAMPLE_16   = 0.000016
    RESAMPLE_32  = 0.000032
    RESAMPLE_64  = 0.000064
    RESAMPLE_128  = 0.000128
    RESAMPLE_256 = 0.000256
    RESAMPLE_512 = 0.000512
    RESAMPLE_1024 = 0.001024
    RESAMPLE_2048 = 0.002048
    RESAMPLE_LONGEST = 1

    #  create a constant to convert indexed power to power
    INDEX2POWER = (10.0 * np.log10(2.0) / 256.0)

    #  and one to convert from indexed angles to electrical angles
    INDEX2ELEC = 180.0 / 128.0


    def __init__(self, channel_id, n_pings=100, n_samples=1000, rolling=False,
            chunk_width=500, store_power=True, store_angles=True, max_sample_number=None):
        """
        Creates a new, empty raw_data object. The raw_data class stores raw
        echosounder data from a single channel of an EK60 or ES60/70 system.

        NOTE: power is stored in log form. If you manipulate power values
              directly, make sure they are stored in log form.

        if rolling is True, arrays of size (n_pings, n_samples) are created for power
        and angle data upon instantiation and are filled with NaNs. These arrays are
        fixed in size and if a ping is added beyond the "width" of the array the
        array is "rolled left", and the new ping is added at the end of the array. This
        feature is intended to support streaming data sources such as telegram
        broadcasts and the client/server interface.

        chunk_width specifies the number of columns to add to data arrays when they
        fill up when rolling == False.

        """
        super(raw_data, self).__init__()

        #  we can come up with a better name, but this specifies if we have a fixed data
        #  array size and roll it when it fills or if we expand the array when it fills
        self.rolling_array = bool(rolling)

        #  current_metadata stores a reference to the current channel_metadata object. The
        #  channel_metadata class stores rawfile and channel configuration properties
        #  contained in the .raw file header. When opening a new .raw file, this property
        #  must be updated before appending pings from the new file.
        self.current_metadata = None

        #  the channel ID is the unique identifier of the channel(s) stored in the object
        if (isinstance(channel_id, list)):
            self.channel_id = channel_id
        else:
            self.channel_id = [channel_id]

        #  specify the horizontal size (columns) of the array allocation size.
        self.chunk_width = chunk_width

        #  keep note if we should store the power and angle data
        self.store_power = store_power
        self.store_angles = store_angles

        #  max_sample_number can be set to an integer specifying the maximum number of samples
        #  that will be stored in the sample data arrays.
        self.max_sample_number = max_sample_number

        #  _data_attributes is an internal list that contains the names of all of the class's
        #  "data" properties. The echolab2 package uses this attribute to generalize various
        #  functions that manipulate these data.  Here we *extend* the list that is defined
        #  in the parent class. We don't add the bottom data attributes here. Those are only
        #  added if .bot or .out files are read.
        self._data_attributes += ['channel_metadata',
                                  'transducer_depth',
                                  'frequency',
                                  'transmit_power',
                                  'pulse_length',
                                  'bandwidth',
                                  'sample_interval',
                                  'sound_velocity',
                                  'absorption_coefficient',
                                  'heave',
                                  'pitch',
                                  'roll',
                                  'temperature',
                                  'heading',
                                  'transmit_mode',
                                  'sample_offset',
                                  'sample_count',
                                  'power',
                                  'angles_alongship_e',
                                  'angles_athwartship_e']

        #  if we're using a fixed data array size, we can allocate the arrays now
        if (self.rolling_array):
            #  since we assume rolling arrays will be used in a visual or interactive
            #  application, we initialize the arrays so they can be displayed
            self._create_arrays(n_pings, n_samples, initialize=True)

            #  initialize the ping counter to indicate that our data arrays have been allocated
            self.n_pings = 0

        #  if we're not using fixed arrays, we will initialze them when append_ping is
        #  called for the first time. Until then, the raw_data object will not contain
        #  the data properties.


    def empty_like(self, n_pings):
        """
        empty_like returns a paw_data object with the same general
        characteristics of "this" object  but all of the data arrays are
        filled with NaNs

        Args:
            n_pings: Set n_pings to an integer specifying the number of pings
                in the new object. The vertical axis (both number of samples
                and depth/range values) will be the same as this object.

        """

        #  create an instance of echolab2.EK60.paw_data and set the same
        #  basic properties as this object.
        empty_obj = raw_data(self.channel_id, n_pings=n_pings, n_samples=self.n_samples,
            rolling=self.rolling_array, chunk_width=n_pings, store_power=self.store_power,
            store_angles=self.store_angles, max_sample_number=self.max_sample_number)

        #  and return the empty processed_data object
        return self._like(empty_obj, n_pings, np.nan, empty_times=True)


    def insert(self, obj_to_insert, ping_number=None, ping_time=None,
            insert_after=True, index_array=None):

        #  determine how many pings we're inserting
        if (index_array is None):
            in_idx  = self.get_indices(start_time=ping_time, end_time=ping_time,
                    start_ping=ping_number, end_ping=ping_number)[0]
            n_inserting = self.n_pings - in_idx
        else:
            n_inserting = index_array.shape[0]

        if (obj_to_insert is None):
            #  when obj_to_insert is None, we create automatically create a
            #  matching object that contains no data (all NaNs)
            obj_to_insert = self.empty_like(n_inserting)

        #  check that the data types are the same
        if (not isinstance(obj_to_insert, raw_data)):
            raise TypeError('The object you are inserting must be an instance of EK60.raw_data')

        #  we are now coexisting in harmony - call parent's insert
        super(raw_data, self).insert(obj_to_insert, ping_number=ping_number,
                                     ping_time=ping_time, insert_after=insert_after,
                                     index_array=index_array)


    def append_bot(self, detection_time, detection_depth, reflectivity=None):
        """
        while the name implies otherwise, append_bot actully inserts a bottom detection
        depth into the detected_bottom array for a specified ping time. If the
        time is not matched, the data is ignored.

        When reading .out files you can pass the reflectivity value.

        To keep things simple, you must add the corresponding "ping" data before
        adding the detected bottom depth. If you try to add a bottom value for
        a ping that has yet to be added the matching ping_time will not exist and
        the bottom value will be ignored.
        """
        #  first check if the detected_bottom attribute exists and create if not
        if (not hasattr(self, 'detected_bottom')):
            #  nope - create it
            data = np.full(self.ping_time.shape[0], np.nan)
            self.add_attribute('detected_bottom', data)

        #  if we're storing reflectivity, check if it exists
        if (reflectivity is not None):
            if (not hasattr(self, 'bottom_reflectivity')):
                #  nope - create it
                data = np.full(self.ping_time.shape[0], np.nan)
                self.add_attribute('bottom_reflectivity', data)

        #  determine the array element associated with this ping and
        #  update it with the detection depth and optional reflectivity
        idx_array = self.ping_time == detection_time
        if (np.any(idx_array)):
            self.detected_bottom[idx_array] = detection_depth
            if (reflectivity is not None):
                self.bottom_reflectivity[idx_array] = reflectivity


    def append_ping(self, sample_datagram, start_sample=None, end_sample=None):
        """
        append_ping is called when adding a ping's worth of data to the object. It should accept
        the parsed values from the sample datagram. It will handle the details of managing
        the array sizes, resizing as needed (or rolling in the case of a fixed size). Append ping also
        updates the RawFileData object's end_ping and end_time values for the current file.

        Managing the data array sizes is the bulk of what this method does. It will either resize
        the array is rolling == false or roll the array if it is full and rolling == true.

        The data arrays will change size in 2 ways:

            Adding pings will add columns (or roll the array if all of the columns are filled and
            rolling == true.) This can easily be handled by allocating columns in chunks using
            the resize method of the numpy array and maintaining an index into
            the *next* available column (self.n_pings). Empty pings can be left uninitialized (if
            that is possible with resize) or set to NaN if it is free. If it takes additional steps to
            set to NaN, then just leave them at the default value.

            Changing the recording range or pulse length will either require adding rows (if there
            are more samples) or padding (if there are fewer. If rows are added to the array,
            existing pings will need to be padded with NaNs.

        If rolling == true, we will never resize the array. If a ping has more samples than the
        array has allocated the extra samples will be dropped. In all cases if a ping has fewer
        samples than the array has allocated it should be padded with NaNs.

        """

        #  determine the number of samples in this ping
        if (sample_datagram['angle'] is not None):
            angle_samps = sample_datagram['angle'].shape[0]
        else:
            angle_samps = -1
        if (sample_datagram['power'] is not None):
            power_samps = sample_datagram['power'].shape[0]
        else:
            power_samps = -1

        #  if using dynamic arrays, handle intialization of data arrays when the first ping is added
        if (self.n_pings == -1 and self.rolling_array == False):
            if self.max_sample_number:
                number_samples = self.max_sample_number
            else:
                number_samples = max([angle_samps, power_samps])
            #  create the initial data arrays
            self._create_arrays(self.chunk_width, number_samples)

            #  initialize the ping counter to indicate that our data arrays have been allocated
            self.n_pings  = 0

        #  determine the greatest number of existing samples and the greatest number of
        #  samples in this datagram. In theory the power and angle arrays should always be
        #  the same size but we'll check all to make sure.
        max_data_samples = max(self.power.shape[1],self.angles_alongship_e.shape[1],
                self.angles_athwartship_e.shape[1])
        max_new_samples = max([power_samps, angle_samps])

        #  check if we need to truncate the sample data
        if (self.max_sample_number) and (max_new_samples > self.max_sample_number):
            max_new_samples = self.max_sample_number
            if (angle_samps > 0):
                sample_datagram['angle'] = sample_datagram['angle'][0:self.max_sample_number]
            if (power_samps > 0):
                sample_datagram['power'] = sample_datagram['power'][0:self.max_sample_number]

        #  create 2 variables to store our current array size
        ping_dims = self.ping_time.size
        sample_dims = max_data_samples

        #  check if we need to re-size or roll our data arrays
        if (self.rolling_array == False):
            #  check if we need to resize our data arrays
            ping_resize = False
            sample_resize = False

            #  check the ping dimension
            if (self.n_pings == ping_dims):
                #  need to resize the ping dimension
                ping_resize = True
                #  calculate the new ping dimension
                ping_dims = ping_dims + self.chunk_width

            #  check the samples dimension
            if (max_new_samples > max_data_samples):
                #  need to resize the samples dimension
                sample_resize = True
                #  calculate the new samples dimension
                sample_dims = max_new_samples

            #  determine if we resize
            if (ping_resize or sample_resize):
                #  resize the data arrays
                self.resize(ping_dims, sample_dims)

            #  get an index into the data arrays for this ping and increment our ping counter
            this_ping = self.n_pings
            self.n_pings += 1

        else:
            #  check if we need to roll
            if (self.n_pings == ping_dims - 1):
                #  when a rolling array is "filled" we stop incrementing the ping counter
                #  and repeatedly append pings to the last ping index in the array
                this_ping = self.n_pings

                #  roll our array 1 ping
                self._roll_arrays(1)

        #  insert the channel_metadata object reference for this ping
        self.channel_metadata[this_ping] = self.current_metadata

        #  update the channel_metadata object with this ping number and time
        self.current_metadata.end_ping = self.n_pings
        self.current_metadata.end_time = sample_datagram['timestamp']

        #  now insert the data into our numpy arrays
        self.ping_time[this_ping] = sample_datagram['timestamp']
        self.transducer_depth[this_ping] = sample_datagram['transducer_depth']
        self.frequency[this_ping] = sample_datagram['frequency']
        self.transmit_power[this_ping] = sample_datagram['transmit_power']
        self.pulse_length[this_ping] = sample_datagram['pulse_length']
        self.bandwidth[this_ping] = sample_datagram['bandwidth']
        self.sample_interval[this_ping] = sample_datagram['sample_interval']
        self.sound_velocity[this_ping] = sample_datagram['sound_velocity']
        self.absorption_coefficient[this_ping] = sample_datagram['absorption_coefficient']
        self.heave[this_ping] = sample_datagram['heave']
        self.pitch[this_ping] = sample_datagram['pitch']
        self.roll[this_ping] = sample_datagram['roll']
        self.temperature[this_ping] = sample_datagram['temperature']
        self.heading[this_ping] = sample_datagram['heading']
        self.transmit_mode[this_ping] = sample_datagram['transmit_mode']

        #  do the book keeping if we're storing a subset of samples
        if (start_sample):
            self.sample_offset[this_ping] = start_sample
            if (end_sample):
                self.sample_count[this_ping] = end_sample - start_sample + 1
            else:
                self.sample_count[this_ping] = sample_datagram['count'] - start_sample
        else:
            self.sample_offset[this_ping] = 0
            start_sample = 0
            if (end_sample):
                self.sample_count[this_ping] = end_sample + 1
            else:
                self.sample_count[this_ping] = sample_datagram['count']
                end_sample = sample_datagram['count']

        #  now store the 2d "sample" data
        #      determine what we need to store based on operational mode
        #      1 = Power only, 2 = Angle only 3 = Power & Angle

        #  check if we need to store power data
        if (sample_datagram['mode'] != 2) and (self.store_power):

            #  get the subset of samples we're storing
            power = sample_datagram['power'][start_sample:self.sample_count[this_ping]]

            #  convert the indexed power data to power dB
            power = power.astype(self.sample_dtype) * self.INDEX2POWER

            #  check if we need to pad or trim our sample data
            sample_pad = sample_dims - power.shape[0]
            if (sample_pad > 0):
                #  the data array has more samples than this datagram - we need to pad the datagram
                self.power[this_ping,:] = np.pad(power,(0,sample_pad),
                        'constant', constant_values=np.nan)
            elif (sample_pad < 0):
                #  the data array has fewer samples than this datagram - we need to trim the datagram
                self.power[this_ping,:] = power[0:sample_pad]
            else:
                #  the array has the same number of samples
                self.power[this_ping,:] = power

        #  check if we need to store angle data
        if (sample_datagram['mode'] != 1) and (self.store_angles):
            #  first extract the alongship and athwartship angle data
            #  the low 8 bits are the athwartship values and the upper 8 bits are alongship.
            alongship_e = (sample_datagram['angle'][start_sample:self.sample_count[this_ping]] >> 8).astype('int8')
            athwartship_e = (sample_datagram['angle'][start_sample:self.sample_count[this_ping]] & 0xFF).astype('int8')

            #  and convert from indexed to electrical angles
            alongship_e = alongship_e.astype(self.sample_dtype) * self.INDEX2ELEC
            athwartship_e = athwartship_e.astype(self.sample_dtype) * self.INDEX2ELEC

            #  check if we need to pad or trim our sample data
            sample_pad = sample_dims - athwartship_e.shape[0]
            if (sample_pad > 0):
                #  the data array has more samples than this datagram - we need to pad the datagram
                self.angles_alongship_e[this_ping,:] = np.pad(alongship_e,(0,sample_pad),
                        'constant', constant_values=np.nan)
                self.angles_athwartship_e[this_ping,:] = np.pad(athwartship_e,(0,sample_pad),
                        'constant', constant_values=np.nan)
            elif (sample_pad < 0):
                #  the data array has fewer samples than this datagram - we need to trim the datagram
                self.angles_alongship_e[this_ping,:] = alongship_e[0:sample_pad]
                self.angles_athwartship_e[this_ping,:] = athwartship_e[0:sample_pad]
            else:
                #  the array has the same number of samples
                self.angles_alongship_e[this_ping,:] = alongship_e
                self.angles_athwartship_e[this_ping,:] = athwartship_e


    def get_power(self, **kwargs):
        """
        get_power returns a processed data object that contains the power data. It performs
        all of the required transformations to place the raw power data into a rectangular
        array where all samples share the same thickness and are correctly arranged relative
        to each other.

        This process happens in 3 steps:

                Data are resampled so all samples have the same thickness
                Data are shifted vertically to account for the sample offsets
                Data are then regridded to a fixed time, range grid

        Each step is performed only when required. Calls to this method will return much
        faster if the raw data share the same sample thickness, offset and sound speed.

        If calibration is set to an instance of EK60.calibration_parameters the values in
        that object (if set) will be used when performing the transformations required to
        return the results. If the required parameters are not set in the calibration
        object or if no object is provided, this method will extract these parameters from
        the raw file data.
        """

        #  call the generalized _get_sample_data method requesting the 'power' sample attribute
        p_data, return_indices = self._get_sample_data('power', **kwargs)

        #  set the data type
        p_data.data_type = 'power'

        #  set the is_log attribute
        p_data.is_log = True

        #  and return it
        return p_data


    def _get_power(self, **kwargs):
        """
        _get_power is identical to get_power except that it also returns an index
        array that maps the pings in the processed_data object to the same pings
        in the "this" object. This is used internally.
        """

        #  call the generalized _get_sample_data method requesting the 'power' sample attribute
        p_data, return_indices = self._get_sample_data('power', **kwargs)

        #  set the data type
        p_data.data_type = 'power'

        #  set the is_log attribute
        p_data.is_log = True

        #  and return it
        return p_data, return_indices


    def get_sv(self, **kwargs):
        """
        get_sv returns a processed_data object containing sv

        This is a convenience method which simply calls get_Sv and forces
        the linear keyword to True.
        """

        #  remove the linear keyword
        kwargs.pop('linear', None)

        #  and call get_Sp forcing linear to True
        return self.get_Sv(linear=True, **kwargs)


    def get_Sv(self, calibration=None, linear=False, tvg_correction=True,
            heave_correct=False, return_depth=False,
                **kwargs):
        """
        get_sv returns a processed_data object containing Sv (or sv if linear is
        True).

        The value passed to cal_parameters is a calibration parameters object.
        If cal_parameters == None, the calibration parameters will be extracted
        from the corresponding fields in the raw_data object.

        Sv is calculated as follows:

            Sv = recvPower + 20 log10(Range) + (2 *  alpha * Range) - (10 * ...
                log10((xmitPower * (10^(gain/10))^2 * lambda^2 * ...
                c * tau * 10^(psi/10)) / (32 * pi^2)) - (2 * SaCorrection)

        """

        #  get the power data - this step also resamples and arranges the raw data
        p_data, return_indices = self._get_power(calibration=calibration, **kwargs)

        #  set the data type and is_log attribute
        if (linear):
            attribute_name = 'sv'
            p_data.is_log = False

        else:
            attribute_name = 'Sv'
            p_data.is_log = True
        p_data.data_type = attribute_name

        #  convert power to Sv/sv
        sv_data = self._convert_power(p_data, calibration, attribute_name, linear,
                return_indices, tvg_correction)

        #  set the data attribute in the processed_data object
        p_data.data = sv_data

        #  check if we need to convert to depth
        if (heave_correct or return_depth):
            self._to_depth(p_data, calibration, heave_correct, return_indices)

        return p_data


    def get_sp(self, **kwargs):
        """
        get_sp returns a processed_data object containing sp

        This is a convienience method which simply calls get_Sp and forces
        the linear keyword to True.
        """

        #  remove the linear keyword
        kwargs.pop('linear', None)

        #  and call get_Sp forcing linear to True
        return self.get_Sp(linear=True, **kwargs)


    def get_Sp(self,  calibration=None, linear=False, tvg_correction=False,
            heave_correct=False, return_depth=False,
            **kwargs):
        """
        get_sp returns a processed_data object containing Sp (or sp if linear is
        True).

        Sp is calculated as follows:

             Sp = recvPower + 40 * log10(Range) + (2 *  alpha * Range) - (10 * ...
                 log10((xmitPower * (10^(gain/10))^2 * lambda^2) / (16 * pi^2)))

        By default, TVG range correction is not applied to the data. This
        results in output that is consistent with the Simrad "P" telegram and TS
        data exported from Echoview version 4.3 and later (prior versions applied
        the correction by default).

        If you intend to perform single target detections you must apply the
        TVG range correction at some point in your process. This can be done by
        either setting the tvgCorrection keyword of this function or it can be
        done as part of your single target detection routine.

        """

        #  get the power data - this step also resamples and arranges the raw data
        p_data, return_indices = self._get_power(calibration=calibration, **kwargs)

        #  set the data type
        if (linear):
            attribute_name = 'sp'
            p_data.is_log = False
        else:
            attribute_name = 'Sp'
            p_data.is_log = True
        p_data.data_type = attribute_name

        #  convert
        sp_data = self._convert_power(p_data, calibration, attribute_name, linear,
                return_indices, tvg_correction)

        #  set the data attribute in the processed_data object
        p_data.data = sp_data

        #  check if we need to convert to depth
        if (heave_correct or return_depth):
            self._to_depth(p_data, calibration, heave_correct, return_indices)

        return p_data


    def get_bottom(self, calibration=None, return_indices=None,
            heave_correct=False, return_depth=False, **kwargs):
        """
        get_bottom_depths returns a echolab2 line object containing the sounder
        detected bottom depths.

        The sounder detected bottom depths are computed using the sound speed
        setting at the time of recording. If you are applying a different sound
        speed setting via the calibration argument when

        heave_correct is only used to determine if we need to return depths.

        """

        #  check if the user supplied an explicit list of indices to return
        if isinstance(return_indices, np.ndarray):
            if max(return_indices) > self.ping_time.shape[0]:
                raise ValueError("One or more of the return indices provided exceeds the " +
                        "number of pings in the raw_data object")
        else:
            #  get an array of index values to return
            return_indices = self.get_indices(**kwargs)

        #  We don't heave correct the bottom data but if it is set we know we have
        #  to return depth. We keep the heave_correct keyword for consistency with
        #  the other get_* methods.
        if (heave_correct):
            return_depth = True

        #  extract the recorded sound velocity
        sv_recorded = self.sound_velocity[return_indices]

        #  get the calibration params required for detected depth conversion
        cal_parms = {'sound_velocity':None,
                     'transducer_depth':None}

        #  next, iterate thru the dict, calling the method to extract the values for each parameter
        for key in cal_parms:
            cal_parms[key] = self._get_calibration_param(calibration, key, return_indices)

        #  check if we have to adjust the depth due to a change in sound speed
        if (np.all(np.isclose(sv_recorded, cal_parms['sound_velocity']))):
            converted_depths = self.detected_bottom[return_indices]
        else:
            cf = sv_recorded / cal_parms['sound_velocity']
            converted_depths = cf * self.detected_bottom[return_indices]

        #  check if we're returning range by subtracting a transducer offset.
        if (return_depth == False):
            #  data is recorded as depth - convert to range
            converted_depths -= cal_parms['transducer_depth'][return_indices]

        #  create a line object to return with our adjusted data
        bottom_line = line.line(ping_time=self.ping_time[return_indices],
                data=converted_depths)

        return bottom_line


    def get_physical_angles(self, calibration=None, **kwargs):
        """
        get_physical_angles returns a processed data object that contains the alongship and
        athwartship angle data.

        """

        #  get the electrical angles
        pd_alongship, pd_athwartship, return_indices = \
                self._get_electrical_angles(calibration=calibration, **kwargs)

        #  get the calibration params required for angle conversion
        cal_parms = {'angle_sensitivity_alongship':None,
                     'angle_sensitivity_athwartship':None,
                     'angle_offset_alongship':None,
                     'angle_offset_athwartship':None}

        #  next, iterate thru the dict, calling the method to extract the values for each parameter
        for key in cal_parms:
            cal_parms[key] = self._get_calibration_param(calibration, key, return_indices)

        #  compute the physical angles
        pd_alongship.data[:] = (pd_alongship.data /
                cal_parms['angle_sensitivity_alongship'][:, np.newaxis])
        pd_alongship.data -= cal_parms['angle_offset_alongship'][:, np.newaxis]
        pd_athwartship.data[:] = (pd_athwartship.data /
                cal_parms['angle_sensitivity_athwartship'][:, np.newaxis])
        pd_athwartship.data -= cal_parms['angle_offset_athwartship'][:, np.newaxis]

        #  set the data types
        pd_alongship.data_type = 'angles_alongship'
        pd_athwartship.data_type = 'angles_athwartship'

        #  we do not need to convert to depth here since the electrical_angle data will
        #  already have been converted to depth if requested

        return (pd_alongship, pd_athwartship)


    def get_electrical_angles(self, heave_correct=False, return_depth=False,
            calibration=None, **kwargs):
        """
        get_electrical_angles returns two processed data objects containing the unconverted
        angles_alongship_e, and angles_athwartship_e data.
        """

        #  call the generalized _get_sample_data method requesting the 'angles_alongship_e' sample
        #  attribute. The method will return a reference to anewly created iprocessed_data nstance.
        pd_alongship, return_indices = self._get_sample_data('angles_alongship_e', **kwargs)

        #  do the same for the athwartship data
        pd_athwartship, return_indices = self._get_sample_data('angles_athwartship_e', **kwargs)

        #  set the data type
        pd_alongship.data_type = 'angles_alongship_e'
        pd_athwartship.data_type = 'angles_athwartship_e'

        if (heave_correct or return_depth):
            self._to_depth(pd_alongship, calibration, heave_correct, return_indices)
            self._to_depth(pd_athwartship, calibration, heave_correct, return_indices)

        return (pd_alongship, pd_athwartship)


    def _get_electrical_angles(self, heave_correct=False, return_depth=False,
            calibration=None, **kwargs):
        """
        _get_electrical_angles is identical to get_electrical_angles except that it
        also returns an index array that maps the pings in the processed_data object
        to the same pings in the "this" object. This is used internally.
        """

        #  call the generalized _get_sample_data method requesting the 'angles_alongship_e' sample
        #  attribute. The method will return a reference to anewly created iprocessed_data nstance.
        alongship, return_indices = self._get_sample_data('angles_alongship_e', **kwargs)

        #  We use the "private" insert_into keyword to insert the athwartship_e data into p_data
        kwargs.pop('return_indices', None)
        athwartship, return_indices2 = self._get_sample_data('angles_athwartship_e',
                return_indices=return_indices, **kwargs)

        #  set the data type
        alongship.data_type = 'angles_alongship_e'
        athwartship.data_type = 'angles_athwartship_e'

        if (heave_correct or return_depth):
            self._to_depth(alongship, calibration, heave_correct, return_indices)
            self._to_depth(athwartship, calibration, heave_correct, return_indices)

        return (alongship, athwartship, return_indices)


    def _get_sample_data(self, property_name, calibration=None, resample_interval=RESAMPLE_SHORTEST,
            resample_soundspeed=None, return_indices=None, **kwargs):
        """
        _get_sample_data returns a processed data object that contains the sample data from
        the property name provided. It performs all of the required transformations to place
        the raw data into a rectangular array where all samples share the same thickness
        and are correctly arranged relative to each other.

        This process happens in 3 steps:

                Data are resampled so all samples have the same thickness
                Data are shifted vertically to account for the sample offsets
                Data are then regridded to a fixed time, range grid

        Each step is performed only when required. Calls to this method will return much
        faster if the raw data share the same sample thickness, offset and sound speed.

        If calibration is set to an instance of EK60.calibration_parameters the values in
        that object (if set) will be used when performing the transformations required to
        return the results. If the required parameters are not set in the calibration
        object or if no object is provided, this method will extract these parameters from
        the raw data.

        """

        def get_range_vector(num_samples, sample_interval, sound_speed, sample_offset):
            """
            get_range_vector returns a NON-CORRECTED range vector.
            """
            #  calculate the thickness of samples with this sound speed
            thickness = sample_interval * sound_speed / 2.0
            #  calculate the range vector
            range = (np.arange(0, num_samples) + sample_offset) * thickness

            return range

        #  check if the user supplied an explicit list of indices to return
        if isinstance(return_indices, np.ndarray):
            if max(return_indices) > self.ping_time.shape[0]:
                raise ValueError("One or more of the return indices provided exceeds the " +
                        "number of pings in the raw_data object")
        else:
            #  get an array of index values to return
            return_indices = self.get_indices(**kwargs)

        #  create the processed_data object we will return
        p_data = processed_data.processed_data(self.channel_id, self.frequency[0], None)

        #  populate it with time and ping number
        p_data.ping_time = self.ping_time[return_indices].copy()

        #  get a reference to the data we're operating on
        if (hasattr(self, property_name)):
            data = getattr(self, property_name)
        else:
            raise AttributeError("The attribute name " + property_name + " does not exist.")

        #  populate the calibration parameters required for this method. First, create a dict with key
        #  names that match the attributes names of the calibration parameters we require for this method
        cal_parms = {'sample_interval':None,
                     'sound_velocity':None,
                     'sample_offset':None}

        #  next, iterate thru the dict, calling the method to extract the values for each parameter
        for key in cal_parms:
            cal_parms[key] = self._get_calibration_param(calibration, key, return_indices)

        #  check if we have multiple sample offset values and get the minimum
        unique_sample_offsets = np.unique(cal_parms['sample_offset'][~np.isnan(cal_parms['sample_offset'])])
        min_sample_offset = min(unique_sample_offsets)

        # check if we need to resample our sample data
        unique_sample_interval = np.unique(cal_parms['sample_interval'][~np.isnan(cal_parms['sample_interval'])])
        if (unique_sample_interval.shape[0] > 1):
            #  there are at least 2 different sample intervals in the data - we must resample the data.
            #  Since we're already in the neighborhood, we deal with adjusting sample offsets here too.
            (output, sample_interval) = self._vertical_resample(data[return_indices],
                    cal_parms['sample_interval'], unique_sample_interval, resample_interval,
                    cal_parms['sample_offset'], min_sample_offset, is_power=property_name == 'power')
        else:
            #  we don't have to resample, but check if we need to shift any samples based on their sample offsets.
            if (unique_sample_offsets.shape[0] > 1):
                #  we have multiple sample offsets so we need to shift some of the samples
                output = self._vertical_shift(data[return_indices],
                        cal_parms['sample_offset'], unique_sample_offsets, min_sample_offset)
            else:
                #  the data all have the same sample intervals and sample offsets - simply copy the data as is.
                output = data[return_indices].copy()

            #  and get the sample interval value to use for range conversion below
            sample_interval = unique_sample_interval[0]

        #  check if we have a fixed sound speed
        unique_sound_velocity = np.unique(cal_parms['sound_velocity'])
        if (unique_sound_velocity.shape[0] > 1):
            #  there are at least 2 different sound speeds in the data or provided calibration data.
            #  interpolate all data to the most common range (which is the most common sound speed)
            sound_velocity = None
            n = 0
            for speed in unique_sound_velocity:
            #  determine the sound speed with the most pings
                if (np.count_nonzero(cal_parms['sound_velocity'] == speed) > n):
                   sound_velocity = speed

            #  calculate the target range
            range = get_range_vector(output.shape[1], sample_interval, sound_velocity,
                    min_sample_offset)

            #  get an array of indexes in the output array to interpolate
            pings_to_interp = np.where(cal_parms['sound_velocity'] != sound_velocity)[0]

            #  iterate thru this list of pings to change - interpolating each ping
            for ping in pings_to_interp:
                #  resample using the provided sound speed - calculate the
                resample_range = get_range_vector(output.shape[1], sample_interval,
                        cal_parms['sound_velocity'][ping], min_sample_offset)

                output[ping,:] = np.interp(range, resample_range, output[ping,:])

        else:
            #  we have a fixed sound speed - only need to calculate a single range vector
            sound_velocity = unique_sound_velocity[0]
            range = get_range_vector(output.shape[1], sample_interval,
                    sound_velocity, min_sample_offset)

        #  assign the results to the "data" processed_data object
        p_data.add_attribute('data', output)

        #  calculate the sample thickness in m
        sample_thickness = sample_interval * sound_velocity / 2.0

        #  now assign range, sound_velocity, sample thickness and offset to
        #  the processed_data object.
        p_data.add_attribute('range', range)
        p_data.sound_velocity = sound_velocity
        p_data.sample_thickness = sample_thickness
        p_data.sample_offset = min_sample_offset

        #  return the processed_data object containing the requested data
        return p_data, return_indices


    def _convert_power(self, power_data, calibration, convert_to, linear, return_indices,
            tvg_correction):
        """
        _convert_power is a generalized method for converting power to Sv/sv/Sp/sp
        """

        #  populate the calibration parameters required for this method. First, create a dict with key
        #  names that match the attributes names of the calibration parameters we require for this method
        cal_parms = {'gain':None,
                     'transmit_power':None,
                     'equivalent_beam_angle':None,
                     'pulse_length':None,
                     'absorption_coefficient':None,
                     'sa_correction':None}

        #  next, iterate thru the dict, calling the method to extract the values for each parameter
        for key in cal_parms:
            cal_parms[key] = self._get_calibration_param(calibration, key, return_indices)

        #  get sound_velocity from the power data since get_power might have manipulated this value
        cal_parms['sound_velocity'] = np.empty((return_indices.shape[0]), dtype=self.sample_dtype)
        cal_parms['sound_velocity'].fill(power_data.sound_velocity)

        #  calculate the system gains
        wavelength = cal_parms['sound_velocity'] / power_data.frequency
        if (convert_to in ['sv','Sv']):
            gains = 10 * np.log10((cal_parms['transmit_power'] * (10**(cal_parms['gain']/10.0))**2 * \
                    wavelength**2 * cal_parms['sound_velocity'] * cal_parms['pulse_length'] * \
                    10**(cal_parms['equivalent_beam_angle']/10.0)) /  (32 * np.pi**2))
        else:
            gains = 10 * np.log10((cal_parms['transmit_power'] * (10**(cal_parms['gain']/10.0))**2 * \
                    wavelength**2) / (16 * np.pi**2))

        #  get the range for TVG calculation - if tvg_correction = True we will apply a correction
        #  to the range of 2 * sample thickness. The corrected range is also used for absorption
        #  calculations as well. A corrected range should be used to calculate when converting Power
        #  to Sv/sv and
        if (tvg_correction):
            c_range = power_data.range.copy() - (self.TVG_CORRECTION * power_data.sample_thickness)
            c_range[c_range < 0] = 0
        else:
            c_range = power_data.range

        #  #  calculate time varied gain
        tvg = c_range.copy()
        tvg[tvg <= 0] = 1
        if (convert_to in ['sv','Sv']):
            tvg[:] = 20.0 * np.log10(tvg)
        else:
            tvg[:] = 40.0 * np.log10(tvg)
        tvg[tvg < 0] = 0

        #  calculate absorption - this is the outer product of our corrected range
        #  and 2 * absorption_coefficient. We'll use this for our output array to
        #  minimize the arrays we're creating.
        data = np.outer(2.0 * cal_parms['absorption_coefficient'], c_range)

        #  now add in power and TVG
        data += power_data.data + tvg

        #  subtract the applied gains
        data -= gains[:, np.newaxis]

        #  and apply sa correction for Sv/sv
        if (convert_to in ['sv','Sv']):
            data -= (2.0 * cal_parms['sa_correction'])[:, np.newaxis]

        #  now check if we're returning linear or log values
        if (linear):
            #  convert to linear units (use [:] to operate in-place)
            data[:] = 10**(data / 10.0)

        #  and return the result
        return data


    def _to_depth(self, p_data, calibration, heave_correct, return_indices):
        """
        _to_depth is an internal method that converts data from range to depth and
        optionally applies heave correction.
        """

        #  populate the calibration parameters required for this method. First, create a dict with key
        #  names that match the attributes names of the calibration parameters we require for this method
        cal_parms = {'transducer_depth':None,
                     'heave':None}

        #  next, iterate thru the dict, calling the method to extract the values for each parameter
        for key in cal_parms:
            cal_parms[key] = self._get_calibration_param(calibration, key, return_indices)

        #  check if we're applying heave correction and/or returning depth by applying a
        #  transducer offset.
        if (heave_correct):
            #  heave correction implies returning depth - determine the vertical shift per-ping
            vert_shift = cal_parms['heave'] + cal_parms['transducer_depth']
        else:
            #  we're only converting to depth, determine the vertical shift per-ping only applying
            #  the transducer draft
            vert_shift = cal_parms['transducer_depth']

        #  now shift the pings
        p_data.shift_pings(vert_shift, to_depth=True)


    def _get_calibration_param(self, cal_object, param_name, return_indices, dtype='float32'):
        """
        _get_calibration_param interrogates the provided cal_object for the provided param_name
        property and returns the parameter values based on what it finds. It handles 4 cases:

            If the user has provided a scalar calibration value, the function will return
            a 1D array the length of return_indices filled with that scalar.

            If the user has provided a 1D array the length of return_indices it will return
            that array without modification.

            If the user has provided a 1D array the length of self.ping_time, it will
            return a 1D array the length of return_indices that is the subset of this data
            defined by the return_indices index array.

            Lastly, if the user has not provided anything, this function will return a
            1D array the length of return_indices filled with data extracted from the raw
            data object.
        """

        #  check if the calibration object has the attribute we're looking for
        use_cal_object = False
        if (cal_object and hasattr(cal_object, param_name)):
            #  try to get the parameter from the calibration object
            param = getattr(cal_object, param_name)
            if (param is not None):
                use_cal_object = True

        if (use_cal_object):
            #  the cal object seems to have our data - give it a go

            #  check if the input param is an numpy array
            if isinstance(param, np.ndarray):
                #  check if it is a single value array
                if (param.shape[0] == 1):
                    param_data = np.empty((return_indices.shape[0]), dtype=dtype)
                    param_data.fill(param)
                #  check if it is an array the same length as contained in the raw data
                elif (param.shape[0] == self.ping_time.shape[0]):
                    #  cal params provided as full length array, get the selection subset
                    param_data = param[return_indices]
                #  check if it is an array the same length as return_indices
                elif (param.shape[0] == return_indices.shape[0]):
                    #  cal params provided as a subset so no need to index with return_indices
                    param_data = param
                else:
                    #  it is an array that is the wrong shape
                    raise ValueError("The calibration parameter array " + param_name +
                            " is the wrong length.")
            #  not an array - check if it is a scalar int or float
            elif (type(param) == int or type(param) == float or type(param) == np.float64):
                    param_data = np.empty((return_indices.shape[0]), dtype=dtype)
                    param_data.fill(param)
            else:
                #  invalid type provided
                raise ValueError("The calibration parameter " + param_name +
                        " must be an ndarray or scalar float.")
        else:
            #  Parameter is not provided in the calibration object, copy it from the raw data.
            #  Calibration parameters are found directly in the raw_data object and they are
            #  in the channel_metadata objects. If we don't find it directly in raw_data then
            #  we need to fish it out of the channel_metadata objects.
            try:
                #  first check if this parameter is a direct property in raw_data
                self_param = getattr(self, param_name)
                #  it is - return a view of the subset of data we're interested in
                param_data = self_param[return_indices]
            except:
                #  It is not a direct property so it must be in the channel_metadata object.
                #  Create the return array
                param_data = np.empty((return_indices.shape[0]), dtype=dtype)
                #  create a counter to use to index the return array. We can't use the
                #  index value from return_indices since these values may be re-ordered
                ret_idx = 0
                #  then populate with the data found in the channel_metadata objects

                for idx in return_indices:
                    #  sa_correction is annoying - have to dig out of the table
                    if (isinstance(self.channel_metadata[idx], channel_metadata)):
                        if (param_name == 'sa_correction'):
                            sa_table = getattr(self.channel_metadata[idx],'sa_correction_table')
                            pl_table = getattr(self.channel_metadata[idx],'pulse_length_table')
                            param_data[ret_idx] = sa_table[np.where(np.isclose(pl_table,self.pulse_length[idx]))[0]][0]
                        else:
                            param_data[ret_idx] = getattr(self.channel_metadata[idx],param_name)
                    else:
                        param_data[ret_idx] = np.nan
                    #  increment the index counter
                    ret_idx += 1

        return param_data


    def _create_arrays(self, n_pings, n_samples, initialize=False):
        """
        _create_arrays is an internal method that initializes the raw_data data arrays.
        Note that all "data" arrays must be numpy arrays.
        """

        #  first, create uninitialized arrays
        self.ping_time = np.empty((n_pings), dtype='datetime64[ms]')
        self.channel_metadata = np.empty((n_pings), dtype='object')
        self.transducer_depth = np.empty((n_pings), np.float32)
        self.frequency = np.empty((n_pings), np.float32)
        self.transmit_power = np.empty((n_pings), np.float32)
        self.pulse_length = np.empty((n_pings), np.float32)
        self.bandwidth = np.empty((n_pings), np.float32)
        self.sample_interval = np.empty((n_pings), np.float32)
        self.sound_velocity = np.empty((n_pings), np.float32)
        self.absorption_coefficient = np.empty((n_pings), np.float32)
        self.heave = np.empty((n_pings), np.float32)
        self.pitch = np.empty((n_pings), np.float32)
        self.roll = np.empty((n_pings), np.float32)
        self.temperature = np.empty((n_pings), np.float32)
        self.heading = np.empty((n_pings), np.float32)
        self.transmit_mode = np.empty((n_pings), np.uint8)
        self.sample_offset =  np.empty((n_pings), np.uint32)
        self.sample_count = np.empty((n_pings), np.uint32)
        if (self.store_power):
            self.power = np.empty((n_pings, n_samples), dtype=self.sample_dtype, order='C')
            self.n_samples = n_samples

        if (self.store_angles):
            self.angles_alongship_e = np.empty((n_pings, n_samples), dtype=self.sample_dtype, order='C')
            self.angles_athwartship_e = np.empty((n_pings, n_samples), dtype=self.sample_dtype, order='C')
            self.n_samples = n_samples

        #  check if we should initialize them
        if (initialize):
            self.ping_time.fill(np.datetime64('NaT'))
            #  channel_metadata is initialized when using np.empty
            self.transducer_depth.fill(np.nan)
            self.frequency.fill(np.nan)
            self.transmit_power.fill(np.nan)
            self.pulse_length.fill(np.nan)
            self.bandwidth.fill(np.nan)
            self.sample_interval.fill(np.nan)
            self.sound_velocity.fill(np.nan)
            self.absorption_coefficient.fill(np.nan)
            self.heave.fill(np.nan)
            self.pitch.fill(np.nan)
            self.roll.fill(np.nan)
            self.temperature.fill(np.nan)
            self.heading.fill(np.nan)
            self.transmit_mode.fill(0)
            self.sample_offset.fill(0)
            self.sample_count.fill(0)
            if (self.store_power):
                self.power.fill(np.nan)
            if (self.store_angles):
                self.angles_alongship_e.fill(np.nan)
                self.angles_athwartship_e.fill(np.nan)


    def __str__(self):
        """
        reimplemented string method that provides some basic info about the raw_data object
        """

        #  print the class and address
        msg = str(self.__class__) + " at " + str(hex(id(self))) + "\n"

        #  print some more info about the EK60 instance
        n_pings = len(self.ping_time)
        if (n_pings > 0):
            msg = msg + "                channel(s): ["
            for channel in self.channel_id:
                msg = msg + channel + ", "
            msg = msg[0:-2] + "]\n"
            msg = msg + "    frequency (first ping): " + str(self.frequency[0])+ "\n"
            msg = msg + " pulse length (first ping): " + str(self.pulse_length[0])+ "\n"
            msg = msg + "           data start time: " + str(self.ping_time[0])+ "\n"
            msg = msg + "             data end time: " + str(self.ping_time[n_pings-1])+ "\n"
            msg = msg + "           number of pings: " + str(n_pings)+ "\n"
            if (self.store_power):
                n_pings,n_samples = self.power.shape
                msg = msg + ("    power array dimensions: (" + str(n_pings)+ "," +
                        str(n_samples) +")\n")
            if (self.store_angles):
                n_pings,n_samples = self.angles_alongship_e.shape
                msg = msg + ("    angle array dimensions: (" + str(n_pings)+ "," +
                        str(n_samples) +")\n")
        else:
            msg = msg + ("  RawData object contains no data\n")

        return msg


class channel_metadata(object):
    """
    The channel_metadata class stores the channel configuration data as well as
    some metadata about the file. One of these is created for each channel for
    every .raw file read.

    References to instances of these objects are stored in the raw_data class.

    """

    def __init__(self, file, config_datagram, survey_name, transect_name, sounder_name, version,
                start_ping, start_time, extended_configuration=None):

        #  split the filename
        file = os.path.normpath(file).split(os.path.sep)

        #  store the base filename and path separately
        self.data_file = file[-1]
        self.data_file_path = os.path.sep.join(file[0:-1])

        #  define some basic metadata properties
        self.start_ping = start_ping
        self.end_ping = 0
        self.start_time = start_time
        self.end_time = None

        #  we will replicate the ConfigurationHeader struct here since there
        #  is no better place to store it
        self.survey_name = ''
        self.transect_name = ''
        self.sounder_name = ''
        self.version = ''

        #  store the ME70 extended configuration XML string
        self.extended_configuration = extended_configuration

        #  the GPT firmware version used when recording this data
        self.gpt_firmware_version = config_datagram['gpt_software_version']

        #  the beam type for this channel - split or single
        self.beam_type = config_datagram['beam_type']

        #  the channel frequency in Hz
        self.frequency_hz = config_datagram['frequency']

        #  the system gain when the file was recorded
        self.gain = config_datagram['gain']

        #  beam calibration properties
        self.equivalent_beam_angle = config_datagram['equivalent_beam_angle']
        self.beamwidth_alongship = config_datagram['beamwidth_alongship']
        self.beamwidth_athwartship = config_datagram['beamwidth_athwartship']
        self.angle_sensitivity_alongship = config_datagram['angle_sensitivity_alongship']
        self.angle_sensitivity_athwartship = config_datagram['angle_sensitivity_athwartship']
        self.angle_offset_alongship = config_datagram['angle_offset_alongship']
        self.angle_offset_athwartship = config_datagram['angle_offset_athwartship']

        #  transducer installation/orientation parameters
        self.pos_x = config_datagram['pos_x']
        self.pos_y = config_datagram['pos_y']
        self.pos_z = config_datagram['pos_z']
        self.dir_x = config_datagram['dir_x']
        self.dir_y = config_datagram['dir_y']
        self.dir_z = config_datagram['dir_z']

        #  the possile pulse lengths for the recording system
        self.pulse_length_table = config_datagram['pulse_length_table']
        self.spare2 = config_datagram['spare2']
        #  the gains set for each of the system pulse lengths
        self.gain_table = config_datagram['gain_table']
        self.spare3 = config_datagram['spare3']
        #  the sa correction values set for each pulse length
        self.sa_correction_table = config_datagram['sa_correction_table']
        self.spare4 = config_datagram['spare4']


class calibration_parameters(object):
    """
    The calibration_parameters class contains parameters required for transforming
    power and electrical angle data to Sv/sv TS/SigmaBS and physical angles.

    When converting raw data to power, Sv/sv, Sp/sp, or to physical angles you have
    the option of passing a calibration object containing the data you want
    used during these conversions. To use this object you create an instance and
    populate the attributes with your calibration data.

    You can provide the data in 2 forms:
        As a scalar - the single value will be used for all pings
        As a vector - a vector of values as long as the number of pings
            in the raw_data object where the first value will be used
            with the first ping, the second with the second, and so on.

    If you set any attribute to None, that attribute's valyes will be obtained
    from the raw_data object which contains the value at the time of recording.
    If you do not pass a calibration_parameters object to the conversion methods
    *all* of the cal parameter values will be extracted from the raw_data object.

    """

    def __init__(self):

        #  set the initial calibration property values
        self.channel_id = None

        self.sample_offset = None
        self.sound_velocity = None
        self.sample_interval = None
        self.absorption_coefficient = None
        self.heave = None
        self.equivalent_beam_angle = None
        self.gain  = None
        self.sa_correction = None
        self.transmit_power = None
        self.pulse_length = None
        self.angle_sensitivity_alongship = None
        self.angle_sensitivity_athwartship = None
        self.angle_offset_alongship = None
        self.angle_offset_athwartship = None
        self.transducer_depth = None

        #  create a list that contains the attribute names of the parameters
        self._parms = ['sample_interval',
                       'sound_velocity',
                       'sample_offset',
                       'transducer_depth',
                       'heave',
                       'gain',
                       'transmit_power',
                       'equivalent_beam_angle',
                       'pulse_length',
                       'absorption_coefficient',
                       'sa_correction',
                       'angle_sensitivity_alongship',
                       'angle_sensitivity_athwartship',
                       'angle_offset_alongship',
                       'angle_offset_athwartship']


    def from_raw_data(self, raw_data, return_indices=None):
        """
        from_raw_data populates the calibration object with values
        extracted from a raw_data object.
        """

        #  set the channel_id
        self.channel_id = raw_data.channel_id

        #  if we're not given specific indices, grab everything
        if (return_indices is None):
            return_indices = np.arange(raw_data.ping_time.shape[0])

        #  work through the calibration parameters and extract them
        #  from the raw_data object
        for param_name in self._parms:
            #  Calibration parameters are found directly in the raw_data object and they are
            #  in the channel_metadata objects. If we don't find it directly in raw_data then
            #  we need to fish it out of the channel_metadata objects.
            try:
                #  first check if this parameter is a direct property in raw_data
                raw_param = getattr(raw_data, param_name)
                param_data = raw_param[return_indices].copy()
            except:
                #  It is not a direct property so it must be in the channel_metadata object.
                #  Create the return array
                param_data = np.empty((return_indices.shape[0]))
                #  create a counter to use to index the return array. We can't use the
                #  index value from return_indices since these values may be re-ordered
                ret_idx = 0
                #  then populate with the data found in the channel_metadata objects

                for idx in return_indices:
                    #  sa_correction is annoying - have to dig out of the table
                    if (isinstance(raw_data.channel_metadata[idx], channel_metadata)):
                        if (param_name == 'sa_correction'):
                            sa_table = getattr(raw_data.channel_metadata[idx],'sa_correction_table')
                            pl_table = getattr(raw_data.channel_metadata[idx],'pulse_length_table')
                            param_data[ret_idx] = sa_table[np.where(np.isclose(pl_table,raw_data.pulse_length[idx]))[0]][0]
                        else:
                            param_data[ret_idx] = getattr(self.channel_metadata[idx],param_name)
                    else:
                        param_data[ret_idx] = np.nan
                    #  increment the index counter
                    ret_idx += 1

            #  check if we can collapse the vector - if all the values are the same
            #  we set the parameter to a scalar that value
            if (np.all(np.isclose(param_data, param_data[0]))):
                #  this parameters values are all the same
                param_data = param_data[0]

            #  update the attribute
            setattr(self, param_name, param_data)


    def read_ecs_file(self, ecs_file, channel):
        """
        read_ecs_file reads an echoview ecs file and parses out the
        parameters for a given channel.
        """
        pass

