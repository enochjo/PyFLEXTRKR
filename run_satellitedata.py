import numpy as np
import os, fnmatch
import time, datetime, calendar
from pytz import timezone, utc

# Name: Run_TestData.py

# Purpose: Master script for trackig synthetic IR satellite data

# Comments:
# Features are tracked using 5 sets of code (idclouds, trackclouds_singlefile, get_tracknumbers, calc_sat_trackstats, label_celltrack).
# This script controls which pieces of code are run.
# Eventually, idclouds and trackclouds_singlefile will be able to run in parallel.
# If trackclouds_singlefile is run in of tracksingle between 12/20/2009 - 12/31/2009, make two copies of this script, and set startdate - enddate (ex: 20091220 - 20091225, 20091225 - 20091231).
# This is because the first time will not have a tracksingle file produced, overlapping the date makes sure every cloudid file is used.
# The idclouds and trackClouds_singlefile only need to be run once and can be run on portions of the data a time.
# However, get_tracknumbers, calc_set_tracks, and label_celltrack must be run for the entire dataset.

# Author: Orginial IDL version written by Zhe Feng (zhe.feng@pnnl.gov). Adapted to Python by Hannah Barnes (hannah.barnes@pnnl.gov)

##################################################################################################
# Set variables describing data, file structure, and tracking thresholds

# Specify which sets of code to run. (1 = run code, 0 = don't run code)
run_idclouds = 1        # Segment and identify cloud systems
run_tracksingle = 1     # Track single consecutive cloudid files
run_gettracks = 1       # Run trackig for all files
run_finalstats = 1      # Calculate final statistics
run_labelcloud = 1      # Create maps with all events in a tracking having the same number

# Specify version of code using
cloudid_version = 'v1.0'
track_version = 'v1.0'
tracknumber_version = 'v1.0'

# Specify default code version
curr_id_version = 'v1.0'
curr_track_version = 'v1.0'
curr_tracknumbers_version = 'v1.0'

# Specify days to run
startdate = '20110401'
enddate = '20110831'

# Specify tracking parameters
geolimits = np.array([25,-110,51,-70]) # 4-element array with plotting boundaries [lat_min, lon_min, lat_max, lon_max]
pixel_radius = 4.0      # km
timegap = 1.1           # hour
area_thresh = 1000 #64.       # km^2
miss_thresh = 0.2       # Missing data threshold. If missing data in the domain from this file is greater than this value, this file is considered corrupt and is ignored. (0.1 = 10%)
cloudtb_core = 225.          # K
cloudtb_cold = 241.          # K
cloudtb_warm = 261.          # K
cloudtb_cloud = 261.         # K
othresh = 0.5                     # overlap percentage threshold
lengthrange = np.array([2,30])    # A vector [minlength,maxlength] to specify the lifetime range for the tracks
nmaxlinks = 10                    # Maximum number of clouds that any single cloud can be linked to
nmaxclouds = 3000                 # Maximum number of clouds allowed to be in one track
absolutetb_threshs = np.array([160,330])        # k A vector [min, max] brightness temperature allowed. Brightness temperatures outside this range are ignored.
warmanvilexpansion = 1            # If this is set to one, then the cold anvil is spread laterally until it exceeds the warm anvil threshold

# Specify filenames and locations
datavariablename = 'IRBT'
datasource = 'mergedir'
datadescription = 'EUS'
databasename = 'EUS_IR_Subset_'
label_filebase = 'cloudtrack_'

root_path = '/global/homes/h/hcbarnes/Tracking/Satellite/'
data_path = '/global/project/projectdirs/m1867/zfeng/usa/mergedir/Netcdf/2011/'
scratchpath = './'
latlon_file = data_path + 'mcstrack_20110520_0000.nc'

# Specify data structure
dimname = 'nclouds'
numbername = 'convcold_cloudnumber'
typename = 'cloudtype'
npxname = 'ncorecoldpix'
tdimname = 'time'
xdimname = 'lon'
ydimname = 'lat'

######################################################################
# Generate additional settings

# Isolate year
year = startdate[0:5]

# Concatonate thresholds into one variable
cloudtb_threshs = np.hstack((cloudtb_core, cloudtb_cold, cloudtb_warm, cloudtb_cloud))

# Specify additional file locations
#datapath = root_path                            # Location of raw data
tracking_outpath = root_path + 'tracking/'         # Data on individual features being tracked
stats_outpath = root_path + 'stats/'      # Data on track statistics

######################################################################
# Execute tracking scripts

# Create output directories
if not os.path.exists(tracking_outpath):
    os.makedirs(tracking_outpath)

if not os.path.exists(stats_outpath):
    os.makedirs(stats_outpath)

########################################################################
# Calculate basetime of start and end date
TEMP_starttime = datetime.datetime(int(startdate[0:4]), int(startdate[4:6]), int(startdate[6:8]), 0, 0, 0, tzinfo=utc)
start_basetime = calendar.timegm(TEMP_starttime.timetuple())

TEMP_endtime = datetime.datetime(int(enddate[0:4]), int(enddate[4:6]), int(enddate[6:8]), 23, 0, 0, tzinfo=utc)
end_basetime = calendar.timegm(TEMP_endtime.timetuple())

##########################################################################
# Identify clouds / features in the data, if neccesary
if run_idclouds == 1:
    ######################################################################
    # Identify files to process
    print('Identifying raw data files to process.')

    # Isolate all possible files
    allrawdatafiles = fnmatch.filter(os.listdir(data_path), databasename+'*')

    # Loop through files, identifying files within the startdate - enddate interval
    nleadingchar = np.array(len(databasename)).astype(int)

    rawdatafiles = [None]*len(allrawdatafiles)
    files_timestring = [None]*len(allrawdatafiles) 
    files_datestring = [None]*len(allrawdatafiles)
    files_basetime = np.ones(len(allrawdatafiles), dtype=int)*-9999
    filestep = 0
    for ifile in allrawdatafiles:
        TEMP_filetime = datetime.datetime(int(ifile[nleadingchar:nleadingchar+4]), int(ifile[nleadingchar+4:nleadingchar+6]), int(ifile[nleadingchar+6:nleadingchar+8]), int(ifile[nleadingchar+9:nleadingchar+11]), int(ifile[nleadingchar+11:nleadingchar+13]), 0, tzinfo=utc)
        TEMP_filebasetime = calendar.timegm(TEMP_filetime.timetuple())

        if TEMP_filebasetime >= start_basetime and TEMP_filebasetime <= end_basetime:
            rawdatafiles[filestep] = data_path + ifile
            files_timestring[filestep] = ifile[nleadingchar+9:nleadingchar+11] + ifile[nleadingchar+11:nleadingchar+13]
            files_datestring[filestep] = ifile[nleadingchar:nleadingchar+4] + ifile[nleadingchar+4:nleadingchar+6] + ifile[nleadingchar+6:nleadingchar+8]
            files_basetime[filestep] = np.copy(TEMP_filebasetime)
            filestep = filestep + 1

    # Remove extra rows
    rawdatafiles = rawdatafiles[0:filestep]
    files_timestring = files_timestring[0:filestep]
    files_datestring = files_datestring[0:filestep]
    files_basetime = files_basetime[:filestep]

    ##########################################################################
    # Process files
    # Load function
    from idclouds import idclouds_mergedir

    # Generate imput lists
    list_datasource = [datasource]*(filestep-1)
    list_datadescription = [datadescription]*(filestep-1)
    list_datavariablename = [datavariablename]*(filestep-1)
    list_cloudidversion = [cloudid_version]*(filestep-1)
    list_trackingoutpath = [tracking_outpath]*(filestep-1)
    list_latlonfile = [latlon_file]*(filestep-1)
    list_geolimits = np.ones(((filestep-1), 4))*geolimits
    list_startdate = [startdate]*(filestep-1)
    list_enddate = [enddate]*(filestep-1)
    list_pixelradius = np.ones(filestep-1)*pixel_radius
    list_areathresh = np.ones(filestep-1)*area_thresh
    list_cloudtbthreshs = np.ones((filestep-1,4))*cloudtb_threshs
    list_absolutetbthreshs = np.ones(((filestep-1), 2))*absolutetb_threshs
    list_missthresh = np.ones(filestep-1)*miss_thresh
    list_warmanvilexpansion = np.ones(filestep-1)*warmanvilexpansion

    # Call function
    print('Identifying Clouds')
    map(idclouds_mergedir, rawdatafiles, files_datestring, files_timestring, files_basetime, list_datasource, list_datadescription, list_datavariablename, list_cloudidversion, list_trackingoutpath, list_latlonfile, list_geolimits, list_startdate, list_enddate, list_pixelradius, list_areathresh, list_cloudtbthreshs, list_absolutetbthreshs, list_missthresh, list_warmanvilexpansion)
    cloudid_filebase = datasource + '_' + datadescription + '_cloudid' + cloudid_version + '_'

    ## Call function
    #print('Identifying Clouds')
    #for filestep, ifile in enumerate(rawdatafiles):
    #    idclouds_mergedir(ifile, files_datestring[filestep], files_timestring[filestep], files_basetime[filestep], datasource, datadescription, datavariablename, cloudid_version, tracking_outpath, latlon_file, geolimits, startdate, enddate, pixel_radius, area_thresh, cloudtb_threshs, absolutetb_threshs, miss_thresh, warmanvilexpansion)
    #cloudid_filebase = datasource + '_' + datadescription + '_cloudid' + cloudid_version + '_' 

###################################################################
# Link clouds/ features in time adjacent files (single file tracking), if necessary

# Determine if identification portion of the code run. If not, set the version name and filename using names specified in the constants section
if run_idclouds == 0:
    cloudid_filebase =  datasource + '_' + datadescription + '_cloudid' + curr_id_version + '_'

# Call function
if run_tracksingle == 1:
    ################################################################
    # Identify files to process
    print('Identifying cloudid files to process')

    # Isolate all possible files
    allcloudidfiles = fnmatch.filter(os.listdir(tracking_outpath), cloudid_filebase +'*')

    # Put in temporal order
    allcloudidfiles = sorted(allcloudidfiles)

    # Loop through files, identifying files within the startdate - enddate interval
    nleadingchar = np.array(len(cloudid_filebase)).astype(int)

    cloudidfiles = [None]*len(allcloudidfiles)
    cloudidfiles_timestring = [None]*len(allcloudidfiles)
    cloudidfiles_datestring = [None]*len(allcloudidfiles)
    cloudidfiles_basetime = [None]*len(allcloudidfiles)
    cloudidfilestep = 0
    for icloudidfile in allcloudidfiles:
        TEMP_cloudidtime = datetime.datetime(int(icloudidfile[nleadingchar:nleadingchar+4]), int(icloudidfile[nleadingchar+4:nleadingchar+6]), int(icloudidfile[nleadingchar+6:nleadingchar+8]), int(icloudidfile[nleadingchar+9:nleadingchar+11]), int(icloudidfile[nleadingchar+11:nleadingchar+13]), 0, tzinfo=utc)
        TEMP_cloudidbasetime = calendar.timegm(TEMP_cloudidtime.timetuple())

        if TEMP_cloudidbasetime >= start_basetime and TEMP_cloudidbasetime <= end_basetime:
            cloudidfiles[cloudidfilestep] = tracking_outpath + icloudidfile
            cloudidfiles_timestring[cloudidfilestep] = icloudidfile[nleadingchar+9:nleadingchar+11] + icloudidfile[nleadingchar+11:nleadingchar+13]
            cloudidfiles_datestring[cloudidfilestep] = icloudidfile[nleadingchar:nleadingchar+4] + icloudidfile[nleadingchar+4:nleadingchar+6] + icloudidfile[nleadingchar+6:nleadingchar+8] 
            cloudidfiles_basetime[cloudidfilestep] = np.copy(TEMP_cloudidbasetime)
            cloudidfilestep = cloudidfilestep + 1

    # Remove extra rows
    cloudidfiles = cloudidfiles[0:cloudidfilestep]
    cloudidfiles_timestring = cloudidfiles_timestring[0:cloudidfilestep]
    cloudidfiles_datestring = cloudidfiles_datestring[0:cloudidfilestep]
    cloudidfiles_basetime = cloudidfiles_basetime[:cloudidfilestep]

    ################################################################
    # Process files
    # Load function
    from tracksingle import trackclouds_mergedir

    # Generate input lists
    list_trackingoutpath = [tracking_outpath]*(cloudidfilestep-1)
    list_trackversion = [track_version]*(cloudidfilestep-1)
    list_timegap = np.ones(cloudidfilestep-1)*timegap
    list_nmaxlinks = np.ones(cloudidfilestep-1)*nmaxlinks
    list_othresh = np.ones(cloudidfilestep-1)*othresh
    list_startdate = [startdate]*(cloudidfilestep-1)
    list_enddate = [enddate]*(cloudidfilestep-1)

    # Call function
    print('Tracking clouds between single files')

    map(trackclouds_mergedir, cloudidfiles[0:-1], cloudidfiles[1::], cloudidfiles_datestring[0:-1], cloudidfiles_datestring[1::], cloudidfiles_timestring[0:-1], cloudidfiles_timestring[1::], cloudidfiles_basetime[0:-1], cloudidfiles_basetime[1::], list_trackingoutpath, list_trackversion, list_timegap, list_nmaxlinks, list_othresh, list_startdate, list_enddate)
    singletrack_filebase = 'track' + track_version + '_'

    # Call function
    #print('Tracking clouds between single files')

    #for icloudidfile in range(1,cloudidfilestep):
    #    trackclouds_mergedir(cloudidfiles[icloudidfile-1], cloudidfiles[icloudidfile], cloudidfiles_datestring[icloudidfile-1], cloudidfiles_datestring[icloudidfile], cloudidfiles_timestring[icloudidfile-1], cloudidfiles_timestring[icloudidfile], cloudidfiles_basetime[icloudidfile-1], cloudidfiles_basetime[icloudidfile], tracking_outpath, track_version, timegap, nmaxlinks, othresh, startdate, enddate)
    #singletrack_filebase = 'track' + track_version + '_' 

###########################################################
# Track clouds / features through the entire dataset

# Determine if single file tracking code ran. If not, set the version name and filename using names specified in the constants section
if run_tracksingle == 0:
    singletrack_filebase = 'track' + curr_track_version + '_'

# Call function
if run_gettracks == 1:
    # Load function
    from gettracks import gettracknumbers_mergedir

    # Call function
    print('Getting track numbers')
    gettracknumbers_mergedir(datasource, datadescription, tracking_outpath, stats_outpath, startdate, enddate, timegap, nmaxclouds, cloudid_filebase, npxname, tracknumber_version, singletrack_filebase, keepsingletrack=1, removestartendtracks=1)
    tracknumbers_filebase = 'tracknumbers' + tracknumber_version

############################################################
# Calculate final statistics

# Determine if the tracking portion of the code ran. If not, set teh version name and filename using those specified in the constants section
if run_gettracks == 0:
    track_filebase = 'tracknumbers' + curr_tracknumbers_version

# Call function
if run_finalstats == 1:
    # Load function
    from trackstats import trackstats_sat

    # Call satellite version of function
    print('Calculating track statistics')
    trackstats_sat(datasource, datadescription, pixel_radius, latlon_file, geolimits, area_thresh, cloudtb_threshs, absolutetb_threshs, startdate, enddate, cloudid_filebase, tracking_outpath, stats_outpath, track_version, tracknumber_version, tracknumbers_filebase, lengthrange=lengthrange)






