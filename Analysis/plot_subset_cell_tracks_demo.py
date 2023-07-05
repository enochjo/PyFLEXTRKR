"""
Demonstrates ploting cell tracks on radar reflectivity snapshots for a single radar domain.
>python plot_subset_cell_tracks_demo.py -s STARTDATE -e ENDDATE -c CONFIG.yml --radar_lat LAT --radar_lon LON
Optional arguments:
-p 0 (serial), 1 (parallel)
--extent lonmin lonmax latmin latmax (subset domain boundary)
--subset 0 (no), 1 (yes) (subset data before plotting)
--figbasename figure base name (output figure base name)
--figsize width height (figure size in inches)
--output output_directory (output figure directory)
"""
__author__ = "Zhe.Feng@pnnl.gov"
__created_date__ = "08-Jun-2022"

import argparse
import numpy as np
import os, sys
import xarray as xr
import pandas as pd
import math
from scipy.ndimage import binary_erosion, generate_binary_structure
import datetime
import matplotlib as mpl
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
from mpl_toolkits.axes_grid1.inset_locator import inset_axes
import cartopy.crs as ccrs
from cartopy.mpl.ticker import LongitudeFormatter, LatitudeFormatter
# For non-gui matplotlib back end
from matplotlib.backends.backend_agg import FigureCanvasAgg as FigureCanvas
mpl.use('agg')
import dask
from dask.distributed import Client, LocalCluster
import warnings
warnings.filterwarnings("ignore")
from pyflextrkr.ft_utilities import load_config
from pyflextrkr.ft_utilities import load_config, subset_files_timerange
from pyflextrkr.steiner_func import expand_conv_core_nosort
import glob

#-----------------------------------------------------------------------
def parse_cmd_args():
    # Define and retrieve the command-line arguments...
    parser = argparse.ArgumentParser(
        description="Plot cell tracks on radar reflectivity snapshots for a user-defined subset domain."
    )
    parser.add_argument("-s", "--start", help="first time in time series to plot, format=YYYY-mm-ddTHH:MM:SS", required=True)
    parser.add_argument("-e", "--end", help="last time in time series to plot, format=YYYY-mm-ddTHH:MM:SS", required=True)
    parser.add_argument("-c", "--config", help="yaml config file for tracking", required=True)
    parser.add_argument("-p", "--parallel", help="flag to run in parallel (0:serial, 1:parallel)", type=int, default=0)
    parser.add_argument("--radar_lat", help="radar latitude", type=float, required=True)
    parser.add_argument("--radar_lon", help="radar longitude", type=float, required=True)
    parser.add_argument("--extent", nargs='+', help="map extent (lonmin, lonmax, latmin, latmax)", type=float, default=None)
    parser.add_argument("--subset", help="flag to subset data (0:no, 1:yes)", type=int, default=0)
    parser.add_argument("--figbasename", help="output figure base name", default="")
    parser.add_argument("--figsize", nargs='+', help="figure size (width, height) in inches", type=float, default=[8,7])
    parser.add_argument("--output", help="ouput directory", default=None)
    args = parser.parse_args()

    # Put arguments in a dictionary
    args_dict = {
        'start_datetime': args.start,
        'end_datetime': args.end,
        'run_parallel': args.parallel,
        'config_file': args.config,
        'radar_lat': args.radar_lat,
        'radar_lon': args.radar_lon,
        'extent': args.extent,
        'subset': args.subset,
        'figbasename': args.figbasename,
        'figsize': args.figsize,
        'out_dir': args.output,
    }

    return args_dict


#-----------------------------------------------------------------------
def label_perimeter(tracknumber, dilationstructure):
    """
    Labels the perimeter on a 2D map from object tracknumber masks.
    """
    # Get unique tracknumbers that is no nan
    tracknumber_unique = np.unique(tracknumber[~np.isnan(tracknumber)]).astype(np.int32)

    # Make an array to store the perimeter
    tracknumber_perim = np.zeros(tracknumber.shape, dtype=np.int32)

    # Loop over each tracknumbers
    for ii in tracknumber_unique:
        # Isolate the cell mask
        itn = tracknumber == ii
        # Erode the cell by 1 pixel
        itn_erode = binary_erosion(itn, structure=dilationstructure).astype(itn.dtype)
        # Subtract the eroded area to get the perimeter
        iperim = np.logical_xor(itn, itn_erode)
        # Label the perimeter pixels with the track number
        tracknumber_perim[iperim == 1] = ii

    return tracknumber_perim

#-----------------------------------------------------------------------
def calc_cell_center(tracknumber, longitude, latitude, xx, yy):
    """
    Calculates the center location from labeled cells.
    """
    
    # Find unique tracknumbers
    tracknumber_uniqe = np.unique(tracknumber[~np.isnan(tracknumber)])
    num_tracknumber = len(tracknumber_uniqe)
    # Make arrays for cell center locations
    lon_c = np.full(num_tracknumber, np.nan, dtype=float)
    lat_c = np.full(num_tracknumber, np.nan, dtype=float)
    xx_c = np.full(num_tracknumber, np.nan, dtype=float)
    yy_c = np.full(num_tracknumber, np.nan, dtype=float)

    # Loop over each tracknumbers to calculate the mean lat/lon & x/y for their center locations
    for ii, itn in enumerate(tracknumber_uniqe):
        iyy, ixx = np.where(tracknumber == itn)
        lon_c[ii] = np.mean(longitude[tracknumber == itn])
        lat_c[ii] = np.mean(latitude[tracknumber == itn])
        xx_c[ii] = np.mean(xx[ixx])
        yy_c[ii] = np.mean(yy[iyy])
        
    return lon_c, lat_c, xx_c, yy_c, tracknumber_uniqe

#-----------------------------------------------------------------------
def calc_latlon(lon1, lat1, dist, angle):
    """
    Haversine formula to calculate lat/lon locations from distance and angle.
    
    lon1:   longitude in [degree]
    lat1:   latitude in [degree]
    dist:   distance in [km]
    angle:  angle in [degree]
    """

    # Earth radius
    # R_earth = 6378.39  # at Equator [km]
    R_earth = 6374.2  # at 40 degree latitude [km]
#     R_earth = 6356.91  # at the pole [km]

    # Conver degrees to radians
    lat1 = math.radians(lat1)
    lon1 = math.radians(lon1)
    bearing = math.radians(angle)

    lat2 = math.asin(math.sin(lat1) * math.cos(dist/R_earth) +
                     math.cos(lat1) * math.sin(dist/R_earth) * math.cos(bearing))
    lon2 = lon1 + math.atan2(math.sin(bearing) * math.sin(dist/R_earth) * math.cos(lat1),
                             math.cos(dist/R_earth) - math.sin(lat1) * math.sin(lat2))
    lat2 = math.degrees(lat2)
    lon2 = math.degrees(lon2)

    return lon2, lat2

#-----------------------------------------------------------------------
def get_track_stats(trackstats_file, start_datetime, end_datetime, dt_thres):
    """
    Subset tracks statistics data within start/end datetime
    Args:
        trackstats_file: string
            Track statistics file name.
        start_datetime: string
            Start datetime to subset tracks.
        end_datetime: dstring
            End datetime to subset tracks.
        dt_thres: timedelta
            A timedelta threshold to retain tracks.
            
    Returns:
        track_dict: dictionary
            Dictionary containing track stats data.
    """
    # Read track stats file
    dss = xr.open_dataset(trackstats_file)
    stats_starttime = dss.base_time.isel(times=0)
    # Convert input datetime to np.datetime64
    stime = np.datetime64(start_datetime)
    etime = np.datetime64(end_datetime)
    time_res = dss.attrs['time_resolution_hour']

    # Find track initiated within the time window
    idx = np.where((stats_starttime >= stime) & (stats_starttime <= etime))[0]
    ntracks = len(idx)
    print(f'Number of tracks within input period: {ntracks}')

    # Calculate cell lifetime
    lifetime = dss.track_duration.isel(tracks=idx) * time_res

    # # Select long-lived tracks
    # idx_long = np.where(lifetime > lifetime_longtracks)[0]
    # ntracks_long = len(idx_long)
    # lifetime_long = lifetime.isel(tracks=idx_long)
    # print(f'Number of long tracks within input period: {ntracks_long}')

    # Subset these tracks and put in a dictionary
    track_dict = {
        'ntracks' : ntracks,
        'lifetime' : lifetime,
        'cell_bt' : dss['base_time'].isel(tracks=idx),
        'cell_lon' : dss['cell_meanlon'].isel(tracks=idx),
        'cell_lat' : dss['cell_meanlat'].isel(tracks=idx),
        'start_split_tracknumber' : dss['start_split_tracknumber'].isel(tracks=idx),
        'end_merge_tracknumber' : dss['end_merge_tracknumber'].isel(tracks=idx),
        'dt_thres': dt_thres,
        'time_res': time_res,
        # # Long-lived tracks
        # 'lifetime_long': lifetime_long,
        # 'cell_bt_long' : dss['base_time'].isel(tracks=idx_long),
        # 'cell_lon_long' : dss['cell_meanlon'].isel(tracks=idx_long),
        # 'cell_lat_long' : dss['cell_meanlat'].isel(tracks=idx_long),
        # 'start_split_tracknumber_long' : dss['start_split_tracknumber'].isel(tracks=idx_long),
        # 'end_merge_tracknumber_long' : dss['end_merge_tracknumber'].isel(tracks=idx_long),
    }
    
    return track_dict

#-----------------------------------------------------------------------
def plot_map(pixel_dict, plot_info, map_info, track_dict):
    """
    Plotting function.
    Args:
        pixel_dict: dictionary
            Dictionary containing pixel-level variables
        plot_info: dictionary
            Dictionary containing plotting variables
        map_info: dictionary
            Dictionary containing mapping variables
        track_dict: dictionary
            Dictionary containing tracking variables
    Returns:
        fig: object
            Figure object.
    """
    
    # Get pixel data from dictionary
    pixel_bt = pixel_dict['pixel_bt']
    xx = pixel_dict['longitude']
    yy = pixel_dict['latitude']
    dbz_comp = pixel_dict['dbz_comp']
    conv_mask = pixel_dict['conv_mask']
    cell_base = pixel_dict['cell_base']
    Tv = pixel_dict['tv']
    tn_perim_lo = pixel_dict['tn_perim_lo']
    tn_perim_hi = pixel_dict['tn_perim_hi']
    tn_perim    = pixel_dict['tn_perim']
    lon_tn_lo = pixel_dict['lon_tn_lo']
    lon_tn_hi = pixel_dict['lon_tn_hi']
    lon_tn    = pixel_dict['lon_tn']
    lat_tn_lo = pixel_dict['lat_tn_lo']
    lat_tn_hi = pixel_dict['lat_tn_hi']
    lat_tn    = pixel_dict['lat_tn']
    tn = pixel_dict['tn']
    tracknumbers_lo = pixel_dict['tracknumber_unique_lo']
    tracknumbers_hi = pixel_dict['tracknumber_unique_hi']
    tracknumbers    = pixel_dict['tracknumber_unique']
    # Get track data from dictionary
    ntracks = track_dict['ntracks']
    lifetime = track_dict['lifetime']
    cell_bt = track_dict['cell_bt']
    cell_lon = track_dict['cell_lon']
    cell_lat = track_dict['cell_lat']
    dt_thres = track_dict['dt_thres']
    time_res = track_dict['time_res']
    # Get plot info from dictionary
    levels = plot_info['levels']
    cmaps = plot_info['cmaps']
    # titles = plot_info['titles']
    cblabels = plot_info['cblabels']
    cbticks = plot_info['cbticks']
    fontsize = plot_info['fontsize']
    timestr = plot_info['timestr']
    figname = plot_info['figname']
    figsize = plot_info['figsize']

    marker_size = plot_info['marker_size']
    lw_centroid = plot_info['lw_centroid']
    cmap_tracks = plot_info['cmap_tracks']
    cblabel_tracks = plot_info['cblabel_tracks']
    cbticks_tracks = plot_info['cbticks_tracks']
    lev_lifetime = plot_info['lev_lifetime']
    radii = plot_info['radii']
    azimuths = plot_info['azimuths']
    radar_lon = plot_info['radar_lon']
    radar_lat = plot_info['radar_lat']

    # Map domain, lat/lon ticks, background map features
    map_extent = map_info['map_extent']
    lonv = map_info['lonv']
    latv = map_info['latv']

    # Set up track lifetime colors
    cmap_lifetime = plt.get_cmap(cmap_tracks)
    norm_lifetime = mpl.colors.BoundaryNorm(lev_lifetime, ncolors=cmap_lifetime.N, clip=True)
    
    # Set up map projection
    proj = ccrs.PlateCarree()
    
    # Take mean value of perimeter Tv and fill the cell in.
    # tn_tv = np.zeros_like(tn_perim)
    # for itrack in np.unique(tn_perim)[1:]:
    #     tn_tv[tn == itrack] = np.mean(Tv[tn_perim == itrack])
        
    # Now we need to dynamically adjust the perimeter values
    tn_tv = np.zeros(tn_perim.shape)
    for itrack in np.unique(tn_perim)[1:]:
        tn_tv[tn == itrack] = np.mean(Tv[tn_perim == itrack])

    # Set up figure
    mpl.rcParams['font.size'] = fontsize
    mpl.rcParams['font.family'] = 'Roboto'
    fig = plt.figure(figsize=figsize, dpi=300, facecolor='w')
    gs = gridspec.GridSpec(1,2, height_ratios=[1], width_ratios=[1,0.03])
    gs.update(wspace=0.05, hspace=0.05, left=0.1, right=0.9, top=0.92, bottom=0.08)
    ax1 = plt.subplot(gs[0], projection=proj)
    cax1 = plt.subplot(gs[1])

    ax1.set_extent(map_extent, crs=proj)
    ax1.set_aspect('equal', adjustable=None)
    gl = ax1.gridlines(crs=proj, draw_labels=True, linestyle='--', linewidth=0.)
    gl.right_labels = False
    gl.top_labels = False
    if (lonv is not None) & (latv is not None):
        gl.xlocator = mpl.ticker.FixedLocator(lonv)
        gl.ylocator = mpl.ticker.FixedLocator(latv)
    lon_formatter = LongitudeFormatter(zero_direction_label=True)
    lat_formatter = LatitudeFormatter()        
    ax1.xaxis.set_major_formatter(lon_formatter)
    ax1.yaxis.set_major_formatter(lat_formatter)

    # Plot reflectivity
    cmap = plt.get_cmap(cmaps)
    norm_ref = mpl.colors.BoundaryNorm(levels, ncolors=cmap.N, clip=True)
    # dbz_comp = np.ma.masked_where(dbz_comp < min(levels), dbz_comp) # EJ Replace this
    # cf1 = ax1.pcolormesh(xx, yy, dbz_comp, norm=norm_ref, cmap=cmap, transform=proj, zorder=2)
    tn_tv = np.ma.masked_where(tn_tv == 0, tn_tv) 
    cf1 = ax1.pcolormesh(xx, yy, tn_tv, cmap='Reds',vmin = tn_tv.min(),vmax = tn_tv.max(), transform=proj, zorder=2)
    
    # Overplot cell tracknumber perimeters
    
    red_cmap = mpl.colors.ListedColormap(['red'])
    blu_cmap = mpl.colors.ListedColormap(['blue'])
    blk_cmap = mpl.colors.ListedColormap(['black'])
    
    Tn = np.ma.masked_where(tn_perim == 0, tn_perim)
    Tn[Tn > 0] = 10
    tn3 = ax1.pcolormesh(xx, yy, Tn, cmap=blk_cmap, transform=proj, zorder=3)
    
    Tn_lo = np.ma.masked_where(tn_perim_lo == 0, tn_perim_lo)
    Tn_lo[Tn_lo > 0] = 10
    tn1 = ax1.pcolormesh(xx, yy, Tn_lo, cmap=blu_cmap, transform=proj, zorder=3)
    
    Tn_hi = np.ma.masked_where(tn_perim_hi == 0, tn_perim_hi)
    Tn_hi[Tn_hi > 0] = 10
    tn2 = ax1.pcolormesh(xx, yy, Tn_hi, cmap=red_cmap, transform=proj, zorder=3)

    # Plot track centroids and paths
    marker_style_s = dict(edgecolor='k', linestyle='-', marker='o')
    marker_style_m = dict(edgecolor='k', linestyle='-', marker='o')
    marker_style_l = dict(edgecolor='k', linestyle='-', marker='o')
    for itrack in range(0, ntracks):
        # Get duration of the track
        ilifetime = lifetime.values[itrack]
        idur = (ilifetime / time_res).astype(int)
        # Get basetime of the track and the last time
        ibt = cell_bt.values[itrack,:idur]
        ibt_last = np.nanmax(ibt)
        # Compute time difference between current pixel-level data time and the last time of the track
        idt = (pixel_bt - ibt_last).astype('timedelta64[m]')
        # Proceed if time difference is <= threshold
        # This means for tracks that end longer than the time threshold are not plotted
        if (idt <= dt_thres):
            # Find times in track data <= current pixel-level file time
            idx_cut = np.where(ibt <= pixel_bt)[0]
            idur_cut = len(idx_cut)
            if (idur_cut > 0):
                color_vals = np.repeat(ilifetime, idur_cut)
                # Change centroid marker, linewidth based on track lifetime [hour]
                if (ilifetime < 1):
                    lw_c = lw_centroid[0]
                    size_c = marker_size[0]
                    marker_style = marker_style_s
                elif ((ilifetime >= 1) & (ilifetime < 2)):
                    lw_c = lw_centroid[1]
                    size_c = marker_size[1]
                    marker_style = marker_style_m
                elif (ilifetime >= 2):
                    lw_c = lw_centroid[2]
                    size_c = marker_size[2]
                    marker_style = marker_style_l
                else:
                    lw_c = 0
                    size_c = 0
                size_vals = np.repeat(size_c, idur_cut)
                size_vals[0] = size_c * 2   # Make CI symbol size larger
#                 cc = ax1.plot(cell_lon.values[itrack,idx_cut], cell_lat.values[itrack,idx_cut], lw=lw_c, ls='-', color='k', transform=proj, zorder=3)
#                 cl = ax1.scatter(cell_lon.values[itrack,idx_cut], cell_lat.values[itrack,idx_cut], s=size_vals, c=color_vals, 
#                                  norm=norm_lifetime, cmap=cmap_lifetime, transform=proj, zorder=4, **marker_style)
    # Overplot cell tracknumbers at current frame
    for ii in range(0, len(lon_tn_lo)):
        if (lon_tn_lo[ii] > map_extent[0]) & (lon_tn_lo[ii] < map_extent[1]) & \
            (lat_tn_lo[ii] > map_extent[2]) & (lat_tn_lo[ii] < map_extent[3]):
            ax1.text(lon_tn_lo[ii]+0.02, lat_tn_lo[ii]+0.02, f'{tracknumbers_lo[ii]:.0f}', color='k', size=fontsize*0.8, 
                    weight='bold', ha='left', va='center', transform=proj, zorder=4)
    
    for ii in range(0, len(lon_tn_hi)):
        if (lon_tn_hi[ii] > map_extent[0]) & (lon_tn_hi[ii] < map_extent[1]) & \
            (lat_tn_hi[ii] > map_extent[2]) & (lat_tn_hi[ii] < map_extent[3]):
            ax1.text(lon_tn_hi[ii]+0.02, lat_tn_hi[ii]+0.02, f'{tracknumbers_hi[ii]:.0f}', color='k', size=fontsize*0.8, 
                    weight='bold', ha='left', va='center', transform=proj, zorder=4)
                    
    for ii in range(1, len(lon_tn)):
        if (lon_tn[ii] > map_extent[0]) & (lon_tn[ii] < map_extent[1]) & \
            (lat_tn[ii] > map_extent[2]) & (lat_tn[ii] < map_extent[3]):
            ax1.text(lon_tn[ii]+0.02, lat_tn[ii]+0.02, f'{tracknumbers[ii]:.0f}', color='k', size=fontsize*0.8, 
                    weight='bold', ha='left', va='center', transform=proj, zorder=4)
    
    # Plot colorbar for tracks
    cax = inset_axes(ax1, width="100%", height="100%", bbox_to_anchor=(.04, .97, .3, .03), bbox_transform=ax1.transAxes)
    cbinset = mpl.colorbar.ColorbarBase(cax, cmap=cmap_lifetime, norm=norm_lifetime, orientation='horizontal', label=cblabel_tracks)
    cbinset.set_ticks(cbticks_tracks)

    # Plot range circles around radar
    for ii in range(0, len(radii)):
        rr = ax1.tissot(rad_km=radii[ii], lons=radar_lon, lats=radar_lat, n_samples=100, facecolor='None', edgecolor='k', lw=0.4, zorder=3)
    # Plot azimuth lines
    for ii in range(0, len(azimuths)):
        lon2, lat2 = calc_latlon(radar_lon, radar_lat, 200, azimuths[ii])
        ax1.plot([radar_lon,lon2], [radar_lat,lat2], color='k', lw=0.4, transform=ccrs.Geodetic(), zorder=5)
    # Reflectivity colorbar
#     cb1 = plt.colorbar(cf1, cax=cax1, label=cblabels, ticks=cbticks, extend='both')
    cb1 = plt.colorbar(cf1, cax=cax1, extend='both')
    ax1.set_title(timestr)

    # Thread-safe figure output
    canvas = FigureCanvas(fig)
    canvas.print_png(figname)
    fig.savefig(figname)
    
    return fig

#-----------------------------------------------------------------------
def work_for_time_loop(datafile, tfile, track_dict, map_info, plot_info, weak_strong):
    """
    Process data for a single frame and make the plot.
    Args:
        datafile: string
            Pixel-level data filename
        track_dict: dictionary
            Dictionary containing tracking variables
        map_info: dictionary
            Dictionary containing mapping variables
        plot_info: dictionary
            Dictionary containing plotting variables
        weak_strong: dictionary
            Dictionary containing weak/strong cell ids.
    Returns:
        1.
    """
    
    map_extent = map_info.get('map_extent', None)
    figdir = plot_info.get('figdir')
    figbasename = plot_info.get('figbasename')

    # Read pixel-level data
    ds = xr.open_dataset(datafile)
    pixel_bt = ds.time.data
    
    # Read temperature file
    dst = xr.open_dataset(tfile)
    Tv = dst['tv'][0,25,:,:]
    nx = dst.sizes['west_east']
    ny = dst.sizes['south_north']
    ratio = 1/5
    xcoord_out = np.arange(0, nx*ratio, 1)
    ycoord_out = np.arange(0, ny*ratio, 1)
    iTv = Tv.interp(west_east=xcoord_out, south_north=ycoord_out, method='linear', assume_sorted=True, kwargs={"fill_value": "extrapolate"} ).data
    
    # Get map extent from data
    if map_extent is None:
        lonmin = ds['longitude'].min().item()
        lonmax = ds['longitude'].max().item()
        latmin = ds['latitude'].min().item()
        latmax = ds['latitude'].max().item()
        map_extent = [lonmin, lonmax, latmin, latmax]
        map_info['map_extent'] = map_extent

    # Make dilation structure (larger values make thicker outlines)
    # perim_thick = 1
    # dilationstructure = np.zeros((perim_thick+1,perim_thick+1), dtype=int)
    # dilationstructure[1:perim_thick, 1:perim_thick] = 1
    dilationstructure = generate_binary_structure(2,1)

    # Get cell tracknumbers
    tn = ds['tracknumber'].squeeze()

    # Only plot if there is cell in the frame
    if (np.nanmax(tn) > 0):
        # Subset pixel data within the map domain
        if subset == 1:
            map_extent = map_info['map_extent']
            buffer = 0.05  # buffer area for subset
            lonmin, lonmax = map_extent[0]-buffer, map_extent[1]+buffer
            latmin, latmax = map_extent[2]-buffer, map_extent[3]+buffer
            mask = (ds['longitude'] >= lonmin) & (ds['longitude'] <= lonmax) & \
                    (ds['latitude'] >= latmin) & (ds['latitude'] <= latmax)
            xx_sub = mask.where(mask == True, drop=True).lon.data
            yy_sub = mask.where(mask == True, drop=True).lat.data
            lon_sub = ds['longitude'].where(mask == True, drop=True).squeeze()
            lat_sub = ds['latitude'].where(mask == True, drop=True).squeeze()
            dbz_comp = ds['dbz_comp'].where(mask == True, drop=True).squeeze() # EJ
            convmask_sub = ds['conv_mask'].where(mask == True, drop=True).squeeze()
            tracknumber_sub = ds['tracknumber'].where(mask == True, drop=True).squeeze()
        else:
            xx_sub = ds['lon'].data
            yy_sub = ds['lat'].data
            lon_sub = ds['longitude'].data.squeeze()
            lat_sub = ds['latitude'].data.squeeze()
            dbz_comp = ds['dbz_comp'].squeeze() # EJ
            convmask_sub = ds['conv_mask'].squeeze()
            tracknumber_sub = ds['tracknumber'].squeeze()
        
        
        
        radii_expand_post = config["radii_expand_post"]
        dx = config["dx"]
        dy = config["dy"]
        
#         import pdb
#         pdb.set_trace()
        
        tracknumber_tmp = tracknumber_sub.fillna(0)
        tmp, _ = expand_conv_core_nosort(tracknumber_tmp.data, radii_expand_post, dx, dy, min_corenpix=0)
        tracknumber_sub = xr.DataArray(tmp, coords=tracknumber_sub.coords, dims=tracknumber_sub.dims)
        
#         tmp, _ = expand_conv_core_nosort(convmask_sub.data, [1,2,3,4,5], 500, 500, min_corenpix=0)
#         convmask_sub = xr.DataArray(tmp, coords=convmask_sub.coords, dims=convmask_sub.dims)
        
        # EJ        
        iLo = weak_strong['iweak']+1
        iHi = weak_strong['istrong']+1
        mask_lo = np.isin(tracknumber_sub,iLo)
        mask_hi = np.isin(tracknumber_sub,iHi)
        tracknumber_sub_lo = tracknumber_sub.where(mask_lo)
        tracknumber_sub_hi = tracknumber_sub.where(mask_hi)
        
        # Get object perimeters
        tn_perim_lo = label_perimeter(tracknumber_sub_lo.data, dilationstructure)
        tn_perim_hi = label_perimeter(tracknumber_sub_hi.data, dilationstructure)
        tn_perim    = label_perimeter(tracknumber_sub.data, dilationstructure)
        
        # Find average Tv for perimeter, then fill in each cell
#         fname = '/gpfs/wolf/atm131/proj-shared/enochjo/20190129_eda09_tracks/stats/stats_3d_w_20190129.1500_20190129.1800.nc'
#         sx1 = xr.open_mfdataset(fname,combine='nested')
#         CoreArea_up = sx1['CoreArea_up'].load().data
#         updr_base = np.zeros((685,720,35)) # rename later to core_base
# 
#         print('Calculating Updraft Base')
#         for itime in np.arange(0,720):
#             for itracks in np.arange(0,685):
#                 for icore in np.arange(0,35):
#                     vprof = np.where( np.isnan(  CoreArea_up[itracks,itime,:,icore] )==False )[0]
#                     if len(vprof) !=0:
#                         updr_base[itracks,itime,icore] = int(vprof[0])
#         updr_base = updr_base.astype(int)
#         
#         print('Calculating Cell Base')
        cell_base = np.zeros((685,720))
#         for itime in np.arange(0,720):
#             for itrack in np.arange(0,685):
#                 ind = updr_base[itrack,itime,:]>0
#                 if len(ind) !=0:
#                     cell_base[itrack,itime] = np.median(updr_base[itrack,itime,ind])
#             
#         cell_base = cell_base.astype(int)
        

        # Apply tracknumber to conv_mask
        tnconv_lo = tracknumber_sub_lo.where(convmask_sub > 0).data
        tnconv_hi = tracknumber_sub_hi.where(convmask_sub > 0).data
        tnconv    = tracknumber_sub.where(convmask_sub > 0).data

        # Calculates cell center locations
        lon_tn_lo, lat_tn_lo, xx_tn, yy_tn, tnconv_unique_lo = calc_cell_center(tnconv_lo, lon_sub, lat_sub, xx_sub, yy_sub)
        lon_tn_hi, lat_tn_hi, xx_tn, yy_tn, tnconv_unique_hi = calc_cell_center(tnconv_hi, lon_sub, lat_sub, xx_sub, yy_sub)
        lon_tn, lat_tn, xx_tn, yy_tn, tnconv_unique          = calc_cell_center(tnconv, lon_sub, lat_sub, xx_sub, yy_sub)
        
        # titles = [timestr]
        timestr = ds['time'].squeeze().dt.strftime("%Y-%m-%d %H:%M:%S UTC").data
        fignametimestr = ds['time'].squeeze().dt.strftime("%Y%m%d_%H%M%S").data.item()
        figname = f'{figdir}{figbasename}{fignametimestr}.png'

        # Put variables in dictionaries
        pixel_dict = {
            'pixel_bt': pixel_bt,
            'longitude': lon_sub, 
            'latitude': lat_sub, 
            'dbz_comp': dbz_comp,
            'tv': iTv, 
            'tn': tracknumber_sub,
            'cell_base': cell_base,
            'conv_mask': convmask_sub,
            'tn_perim_lo': tn_perim_lo,
            'tn_perim_hi': tn_perim_hi,
            'tn_perim': tn_perim, 
            'lon_tn_lo': lon_tn_lo,
            'lon_tn_hi': lon_tn_hi,
            'lon_tn': lon_tn, 
            'lat_tn_lo': lat_tn_lo,
            'lat_tn_hi': lat_tn_hi, 
            'lat_tn': lat_tn, 
            'tracknumber_unique_lo': tnconv_unique_lo,
            'tracknumber_unique_hi': tnconv_unique_hi,
            'tracknumber_unique': tnconv_unique,
        }
        plot_info['timestr'] = timestr
        plot_info['figname'] = figname

        # Call plotting function
        fig = plot_map(pixel_dict, plot_info, map_info, track_dict)
        plt.close(fig)
        print(figname)

    ds.close()
    return 1



if __name__ == "__main__":

    # Get the command-line arguments...
    args_dict = parse_cmd_args()
    start_datetime = args_dict.get('start_datetime')
    end_datetime = args_dict.get('end_datetime')
    run_parallel = args_dict.get('run_parallel')
    config_file = args_dict.get('config_file')
    radar_lat = args_dict.get('radar_lat')
    radar_lon = args_dict.get('radar_lon')
    map_extent = args_dict.get('extent')
    subset = args_dict.get('subset')
    figbasename = args_dict.get('figbasename')
    figsize = args_dict.get('figsize')
    out_dir = args_dict.get('out_dir')

    # Specify plotting info
    # Reflectivity color levels
    levels = np.arange(-10, 60.1, 5)
    lev_lifetime = np.arange(0.5, 4.01, 0.5)
    # Colorbar ticks & labels
    cbticks = np.arange(-10, 60.1, 5)
    cblabels = 'Composite Reflectivity (dBZ)'
    cblabel_tracks = 'Lifetime (hour)'
    cbticks_tracks = [1,2,3,4]
    # Colormaps
    cmaps = 'gist_ncar'     # Reflectivity
    cmap_tracks = 'Spectral_r'  # Lifetime
    
    plot_info = {
        'levels': levels,
        'lev_lifetime': lev_lifetime,
        'cbticks': cbticks,
        'cbticks_tracks': cbticks_tracks,
        'cblabels': cblabels,
        'cblabel_tracks': cblabel_tracks,
        'fontsize': 13,
        'cmaps': cmaps,
        'cmap_tracks': cmap_tracks,
        'marker_size': [30,30,30],    # track centroid marker size (short, medium, long lived)
        'lw_centroid': [3,3,3],         # track path line width
        'radii': np.arange(20,101,20),  # radii for the radar range rings [km]
        'azimuths': np.arange(0,361,90),   # azimuth angles for HSRHI scans [degree]
        'figbasename': figbasename,
        'figsize': figsize,
        'radar_lon': radar_lon,
        'radar_lat': radar_lat,
    }

    # Customize lat/lon labels
    lonv = None
    latv = None
    # Put map info in a dictionary
    map_info = {
        'map_extent': map_extent,
        'subset': subset,
        'lonv': lonv,
        'latv': latv,
    }

    # Tracks that end longer than this threshold from the current pixel-level frame are not plotted
    # This treshold controls the time window to retain previous tracks
    track_retain_time_min = 15

    # Create a timedelta threshold in minutes
    dt_thres = datetime.timedelta(minutes=track_retain_time_min)

    # Track stats file
    config = load_config(config_file)
    stats_path = config["stats_outpath"]
    pixeltracking_path = config["pixeltracking_outpath"]
    pixeltracking_filebase = config["pixeltracking_filebase"]
    trackstats_filebase = config["trackstats_filebase"]
    startdate = config["startdate"]
    enddate = config["enddate"]
    trackstats_file = f"{stats_path}{trackstats_filebase}{startdate}_{enddate}.nc"
    n_workers = config["nprocesses"]
  
    # Convert datetime string to Epoch time (base time)
    start_basetime = pd.to_datetime(start_datetime).timestamp()
    end_basetime = pd.to_datetime(end_datetime).timestamp()

    # Find all pixel-level files that match the input datetime
    datafiles, \
    datafiles_basetime, \
    datafiles_datestring, \
    datafiles_timestring = subset_files_timerange(
        pixeltracking_path,
        pixeltracking_filebase,
        start_basetime,
        end_basetime,
        time_format="yyyymodd_hhmmss",
    )
    print(f'Number of pixel files: {len(datafiles)}')

    # Output figure directory
    if out_dir is None:
        figdir = f'{pixeltracking_path}quicklooks_trackpaths/'
    else:
        figdir = out_dir
    os.makedirs(figdir, exist_ok=True)
    # Add to plot_info dictionary
    plot_info['figdir'] = figdir

    # Get track stats data
    track_dict = get_track_stats(trackstats_file, start_datetime, end_datetime, dt_thres)
    
    # Get subset information (EJ)
    dss   = xr.open_dataset(trackstats_file)
    split = dss['start_split_tracknumber']
    merge = dss['end_merge_tracknumber']
    track_duration = dss['track_duration']
    start_btime    = dss['start_basetime']
    cell_meanlon = dss['cell_meanlon'].mean(dim='times')
    
    sub = np.where((track_duration >= 21)\
    & (start_btime!=np.datetime64('2019-01-29T15:00:15.000000000')) \
    & (cell_meanlon>-64.9) & (np.isnan(split)) & (np.isnan(merge))  )[0]
    
#     sub   = np.where((track_duration >= 21) & (track_duration <= 41) \
#     & (cell_meanlon>-64.9) & (np.isnan(split)) & (np.isnan(merge)) \
#     & (start_btime!=np.datetime64('2019-01-29T15:00:15.000000000')) )[0]
    
    maxETH_10dbz = dss['maxETH_10dbz'].isel(tracks=sub).max(dim='times')
    pct   = maxETH_10dbz.quantile([0.333,0.666])
    iLo   = np.where(maxETH_10dbz.data<=pct.data[0])[0]
    iHi   = np.where(maxETH_10dbz.data>=pct.data[1])[0]
    
    weak_strong = {'iweak' : sub[iLo],'istrong' : sub[iHi]}
    
    # Import temperature information (EJ)
    dir1 = '/gpfs/wolf/atm131/proj-shared/enochjo/20190129_eda09_interp/'
    dir2 = 'corlasso.cldhamsl.2019012900eda09d4.base.M1.m1.'
    tfiles = sorted(glob.glob(dir1+dir2+'*.nc'))[1:]

    # Serial option
    if run_parallel == 0:
        for ifile in range(len(datafiles)):
            print(datafiles[ifile])
            result = work_for_time_loop(datafiles[ifile], tfiles[ifile], track_dict, map_info, plot_info, weak_strong)

    # Parallel option
    elif run_parallel == 1:
        # Set Dask temporary directory for workers
        dask_tmp_dir = config.get("dask_tmp_dir", "./")
        dask.config.set({'temporary-directory': dask_tmp_dir})
        # Initialize dask
        cluster = LocalCluster(n_workers=n_workers, threads_per_worker=1)
        client = Client(cluster)
        results = []
        for ifile in range(len(datafiles)):
            print(datafiles[ifile])
            result = dask.delayed(work_for_time_loop)(datafiles[ifile], tfiles[ifile], track_dict, map_info, plot_info, weak_strong)
            results.append(result)

        # Trigger dask computation
        final_result = dask.compute(*results)
    
    else:
        sys.exit('Valid parallelization flag not provided')