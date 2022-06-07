# CASA script
# tested on CASA 6.2.1.7

# modules
import os
import sys
import numpy as np
import glob

sys.path.append(os.environ.get('CASA_AU_PATH'))
import analysisUtils as aU
import almaqa2csg as csg

class QSOanalysis():

    def __init__(self,tarfilename,casacmd='casa',casacmdforuvfit='casa',spacesave=False,workingDir=None):
        self.tarfilename = tarfilename
        self.workingDir = workingDir
        self.spacesave = spacesave
        self.casacmd = casacmd
        self.casacmdforuvfit = casacmdforuvfit

        self.projID = tarfilename.split('_uid___')[0]
        self.asdmname = 'uid___' + (tarfilename.split('_uid___')[1]).replace('.asdm.sdm.tar','')

    def writelog(self,content=''):
        os.system('mkdir -p log')
        os.system('touch ./log/'+self.asdmname+'.analysis.log')
        os.system('echo "'+content+'" >> '+'./log/'+self.asdmname+'.analysis.log')

    # step0: untar & make working dir
    def intial_proc(self,forcerun=False,dryrun=False):

        if dryrun:
            os.chdir(self.asdmname)

        else:
            if self.workingDir!=None:
                os.chdir(self.workingDir)

            if os.path.exists(self.tarfilename):
                os.system('mkdir -p '+self.asdmname)
                os.system('mv '+self.tarfilename+' '+self.asdmname+'/')
                os.chdir(self.asdmname)
                os.system('tar -xvf '+self.tarfilename)

            elif os.path.exists(self.tarfilename+'.gz'):
                os.system('mkdir -p '+self.asdmname)
                os.system('mv '+self.tarfilename+'.gz '+self.asdmname+'/')
                os.chdir(self.asdmname)
                os.system('gzip -d '+self.tarfilename+'.gz')
                os.system('tar -xvf '+self.tarfilename)

            elif os.path.exists(self.asdmname):
                os.chdir(self.asdmname)

                if os.path.exists(self.tarfilename):
                    os.system('tar -xvf '+self.tarfilename)

                elif os.path.exists(self.tarfilename+'.gz'):
                    os.system('gzip -d '+self.tarfilename+'.gz')
                    os.system('tar -xvf '+self.tarfilename)

            else:
                print('Error: You may need to download data.')
                sys.exit()

        self.writelog('step0:OK')

    # step1: importasdm
    def importasdm(self,dryrun=False):

        asdmfile = glob.glob('./' + self.projID + '/*/*/*/raw/*')[0]
        os.system('ln -sf '+asdmfile+' .')
        visname = (os.path.basename(asdmfile)).replace('.asdm.sdm','.ms')

        kw_importasdm = {
            'asdm':os.path.basename(asdmfile),
            'vis':visname,
            'asis':'Antenna Station Receiver Source CalAtmosphere CalWVR CorrelatorMode SBSummary',
            'bdfflags':True,
            'lazy':True,
            'flagbackup':False,
            }

        if not dryrun:

            from casatasks import importasdm
            os.system('rm -rf '+kw_importasdm['vis'])
            importasdm(**kw_importasdm)

        try:
            self.spws = aU.getScienceSpws(vis=visname).split(",")
            os.system('mkdir -p tempfiles')
            np.save('tempfiles/spws.npy',np.array(self.spws))

        except:
            self.spws = np.load('tempfiles/spws.npy')

        self.asdmfile = asdmfile
        self.visname = visname

        self.writelog('step1:OK')

    # step2: generate calib script
    def gen_calib_script(self,dryrun=False):
        refant = aU.commonAntennas(self.visname)
        kw_generateReducScript = {
            'msNames':self.visname,
            'refant':refant[0],
            'corrAntPos':False,
            }

        if not dryrun:
            csg.generateReducScript(**kw_generateReducScript)

        self.refant = refant
        self.dish_diameter = aU.almaAntennaDiameter(refant[0])

        self.writelog('step2:OK')

    # step3: remove TARGET observations
    def remove_target(self,dryrun=False):
        IntentListASDM = aU.getIntentsFromASDM(self.asdmfile)

        IntentList = []
        for intfield in list(IntentListASDM):
            IntentList = IntentList + IntentListASDM[intfield]

        listOfIntents_init = (np.unique(IntentList)[np.unique(IntentList)!='OBSERVE_TARGET'])

        if not dryrun:
            os.system('rm -rf '+self.visname+'.org')
            os.system('mv '+self.visname+' '+self.visname+'.org')
            kw_mstransform = {
                'vis':self.visname+'.org',
                'outputvis':self.visname,
                'datacolumn':'all',
                'intent':'*,'.join(listOfIntents_init)+'*',
                'keepflags':True
                }

            from casatasks import mstransform
            os.system('rm -rf '+kw_mstransform['outputvis'])
            os.system('rm -rf '+kw_mstransform['outputvis']+'.flagversions')
            mstransform(**kw_mstransform)

        self.writelog('step3:OK')

    # step4: do Calibration
    def doCalib(self,dryrun=False):

        if not dryrun:
            cmdfile = self.visname + '.scriptForCalibration.py'

            checksteps = open(cmdfile,'r')
            syscalcheck = checksteps.readlines().copy()[21]
            checksteps.close()

            f = open(cmdfile.replace('.py','.part.py'),'w')
            if syscalcheck.split(':')[1].split("'")[1] == 'Application of the bandpass and gain cal tables':
                f.write('mysteps = [0,1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16]'+'\n')
            else:
                f.write('mysteps = [0,1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17]'+'\n')
            f.write('applyonly = True'+'\n')
            f.write('execfile('+'"'+cmdfile+'"'+',globals())'+'\n')
            f.close()

            cmd = '"' + 'execfile('+"'"+cmdfile.replace('.py','.part.py')+"'"+')' +'"'
            os.system(self.casacmd+' --nologger --nogui -c '+cmd)

        self.fields = np.unique(aU.getCalibrators(vis=self.visname+'.split'))

        self.beamsize = aU.estimateSynthesizedBeam(self.visname+'.split')
        from casatools import synthesisutils
        su = synthesisutils()

        if self.dish_diameter > 10.:
            # 12m
            self.imsize = su.getOptimumSize(int(120./self.beamsize*5))
        else:
            # 7m
            self.imsize = su.getOptimumSize(int(180./self.beamsize*5))

        self.cell = '{:.3f}'.format(self.beamsize/5) + 'arcsec'

        self.writelog('step4:OK')

    def init_spacesave(self,dryrun=False):

        if not dryrun:
            if self.spacesave:
                os.system('rm -rf '+self.visname)
                os.system('rm -rf '+self.visname+'.org')
                os.system('rm -rf '+self.visname+'.flagversions')
                os.system('rm -rf '+self.visname+'.tsys')
                os.system('rm -rf '+self.visname+'.wvr*')
                os.system('rm -rf '+self.visname+'.*.png')
                os.system('rm -rf '+self.visname+'.split.*')
                os.system('rm *.asdm.sdm')
                os.system('rm -rf '+self.projID)

    # step5-1: split calibrator observations
    def uvfit_splitQSO(self,spw,field,dryrun=False):

        self.spw = spw
        self.field = field

        kw_mstransform = {
            'vis':self.visname+'.split',
            'outputvis':'calibrated/'+self.visname+'.split.'+self.field+'.spw_'+self.spw,
            'datacolumn':'corrected',
            'spw':spw,
            'field':field,
            'intent':'*ON_SOURCE*',
            'keepflags':False,
            'reindex':True,
            }

        if not dryrun:
            os.system('mkdir -p calibrated')
            os.system('rm -rf '+kw_mstransform['outputvis'])
            os.system('rm -rf '+kw_mstransform['outputvis']+'.listobs')

            from casatasks import mstransform,listobs
            mstransform(**kw_mstransform)
            listobs(vis=kw_mstransform['outputvis'],listfile=kw_mstransform['outputvis']+'.listobs')

    def uvfit_splitQSO_allspw(self,field,dryrun=False):

        self.spw = 'all'
        self.field = field

        kw_split = {
            'vis':self.visname+'.split',
            'outputvis':'calibrated/'+self.visname+'.split.'+self.field+'.spw_'+self.spw+'.tmp',
            'datacolumn':'corrected',
            'spw':','.join(self.spws),
            'width':10000,
            'field':field,
            'intent':'*ON_SOURCE*',
            'keepflags':False,
            }

        kw_mstransform = {
            'vis':kw_split['outputvis'],
            'outputvis':'calibrated/'+self.visname+'.split.'+self.field+'.spw_'+self.spw+'.tmp2',
            'datacolumn':'all',
            'combinespws':True,
            'field':field,
            'keepflags':False,
            'reindex':True,
            }

        kw_split2 = {
            'vis':kw_mstransform['outputvis'],
            'outputvis':'calibrated/'+self.visname+'.split.'+self.field+'.spw_'+self.spw,
            'datacolumn':'all',
            'width':10000,
            'field':field,
            'intent':'*ON_SOURCE*',
            'keepflags':False,
            }

        if not dryrun:
            os.system('mkdir -p calibrated')
            os.system('rm -rf '+kw_split['outputvis'])
            os.system('rm -rf '+kw_split['outputvis']+'.listobs')
            os.system('rm -rf '+kw_mstransform['outputvis'])
            os.system('rm -rf '+kw_mstransform['outputvis']+'.listobs')
            os.system('rm -rf '+kw_split2['outputvis'])
            os.system('rm -rf '+kw_split2['outputvis']+'.listobs')

            from casatasks import split,listobs,mstransform
            split(**kw_split)
            listobs(vis=kw_split['outputvis'],listfile=kw_split['outputvis']+'.listobs')
            mstransform(**kw_mstransform)
            listobs(vis=kw_mstransform['outputvis'],listfile=kw_mstransform['outputvis']+'.listobs')
            if aU.getNChanFromCaltable(kw_mstransform['outputvis'])[0] > 1:
                split(**kw_split2)
            else:
                os.system('ln -sf '+kw_split2['vis']+' '+kw_split2['outputvis'])
            listobs(vis=kw_split2['outputvis'],listfile=kw_split2['outputvis']+'.listobs')

            os.system('rm -rf '+kw_split['outputvis'])
            os.system('rm -rf '+kw_split['outputvis']+'.listobs')
            os.system('rm -rf '+kw_mstransform['outputvis'])
            os.system('rm -rf '+kw_mstransform['outputvis']+'.listobs')


    # step5-2: create model column
    def uvfit_createcol(self,modelcol=True,dryrun=False):

        if not dryrun:
            kw_clearcal = {
                'vis':'calibrated/'+self.visname+'.split.'+self.field+'.spw_'+self.spw,
                'addmodel':modelcol,
                }

            from casatasks import clearcal
            clearcal(**kw_clearcal)

    #step5-3: do uvmultifit
    def uvfit_uvmultifit(self,intent=None,write="",column='data',mfsfit=True,dryrun=False):

        if not dryrun:
            os.system('mkdir -p tempfiles')
            os.system('mkdir -p specdata')

            if intent == None:
                outfile = self.visname+'.split.'+self.field+'.spw_'+self.spw+'.dat'
            else:
                outfile = self.visname+'.split.'+self.field+'.spw_'+self.spw+'.'+intent+'.dat'

            f = open('./tempfiles/'+outfile.replace('.dat','.kw_uvfit.py'),'w')
            f.write('from NordicARC import uvmultifit as uvm'+'\n')
            f.write('\n')
            f.write('kw_uvfit = {'+'\n')
            f.write('   "vis":"'+'calibrated/'+self.visname+'.split.'+self.field+'.spw_'+self.spw+'",'+'\n')
            f.write('   "spw":"0",'+'\n')
            f.write('   "column":"'+column+'",'+'\n')
            f.write('   "field":"0",'+'\n')
            f.write('   "stokes":"I",'+'\n')
            f.write('   "NCPU":8,'+'\n')
            f.write('   "pbeam":True,'+'\n')
            f.write('   "dish_diameter":'+str(self.dish_diameter)+','+'\n')
            f.write('   "chanwidth":1,'+'\n')
            f.write('   "var":["0,0,p[0]"],'+'\n')
            f.write('   "p_ini":[1.0],'+'\n')
            f.write('   "model":["delta"],'+'\n')
            f.write('   "OneFitPerChannel":'+str((not mfsfit))+','+'\n')
            f.write('   "write":"'+write+'",'+'\n')
            f.write('   "outfile":"./specdata/'+outfile+'",'+'\n')
            f.write('   "bounds":[[0,None]],'+'\n')
            f.write('   }'+'\n')
            f.write('myfit = uvm.uvmultifit(**kw_uvfit)'+'\n')
            f.close()

            "'" + 'execfile("./tempfiles/'+outfile.replace('.dat','.kw_uvfit.py')+'")' + "'"
            cmd = self.casacmdforuvfit+' --nologger --nogui --nologfile -c '+ "'" + 'execfile("./tempfiles/'+outfile.replace('.dat','.kw_uvfit.py')+'")' + "'"
            os.system(cmd)


    # step5-4: gaincal
    def uvfit_gaincal(self,intent='phase',solint='int',solnorm=False,gaintype='G',calmode='p',gaintable='',dryrun=False):

        kw_gaincal = {
            'vis':'calibrated/'+self.visname+'.split.'+self.field+'.spw_'+self.spw,
            'caltable':'./caltables/'+self.visname+'.split.'+self.field+'.spw_'+self.spw+'.'+intent,
            'field':'0',
            'solint':solint,
            'refant':self.refant[0],
            'gaintype':gaintype,
            'calmode':calmode,
            'minsnr':2.0,
            'gaintable':gaintable,
            'solnorm':solnorm,
            }

        if not dryrun:
            os.system('mkdir -p caltables')
            os.system('rm -rf '+kw_gaincal['caltable'])

            from casatasks import gaincal
            gaincal(**kw_gaincal)

        return kw_gaincal['caltable']

    # step5-5: applycal
    def uvfit_applycal(self,gaintable='',dryrun=False):

        if not dryrun:
            kw_applycal = {
                'vis':'calibrated/'+self.visname+'.split.'+self.field+'.spw_'+self.spw,
                'interp':'linear',
                'flagbackup':False,
                'applymode':'calflag',
                'gaintable':gaintable,
                'calwt':False,
                }

            from casatasks import applycal
            applycal(**kw_applycal)

    # step5-6: gainplot
    def uvfit_gainplot(self,type='amp_phase',dryrun=False,allspws=False):

        if not dryrun:
            from casatools import table
            tb = table()
            import matplotlib.pyplot as plt

            if allspws:
                for field in self.fields:

                    spw = 'all'

                    caltablebase = self.asdmname+'.ms.split.'+field+'.spw_'+spw
                    caltable0 = './caltables/' + caltablebase + '.'+type+'_0'
                    caltable1 = './caltables/' + caltablebase + '.'+type+'_1'

                    tb.open(caltable0)
                    Time0  = tb.getcol('TIME').copy()
                    cgain0 = tb.getcol('CPARAM').copy()
                    ant0   = tb.getcol('ANTENNA1') .copy()
                    tb.close()

                    tb.open(caltable1)
                    Time1  = tb.getcol('TIME').copy()
                    cgain1 = tb.getcol('CPARAM').copy()
                    ant1   = tb.getcol('ANTENNA1') .copy()
                    tb.close()

                    if type == 'phase':
                        phase0_0 = np.angle(cgain0[0][0],deg=True)
                        phase0_1 = np.angle(cgain0[1][0],deg=True)
                        phase1   = np.angle(cgain1[0][0],deg=True)
                    elif type == 'amp_phase':
                        phase0_0 = np.abs(cgain0[0][0])
                        phase1   = np.abs(cgain1[0][0])


                    plt.close()
                    titlename = self.asdmname+' '+field+' spw:'+spw
                    plt.title(titlename)
                    plt.scatter((Time0-Time0[0])/60.,phase0_0,c='b',s=2)
                    if type == 'phase':
                        plt.scatter((Time0-Time0[0])/60.,phase0_1,c='b',s=2)
                    plt.scatter((Time1-Time1[0])/60.,phase1,c='r',s=1)
                    plt.xlabel('Time from the first integration [min]')
                    if type == 'phase':
                        plt.ylabel('Gain phase [deg]')
                    elif type == 'amp_phase':
                        plt.ylabel('Gain amplitude')
                    plt.savefig('./caltables/'+caltablebase+'.gainplot.'+type+'.png')
                    plt.savefig('./caltables/'+caltablebase+'.gainplot.'+type+'.pdf')
                    plt.close()

            else:

                for field in self.fields:
                    for spw in self.spws:
                        caltablebase = self.asdmname+'.ms.split.'+field+'.spw_'+spw
                        caltable0 = './caltables/' + caltablebase + '.'+type+'_0'
                        caltable1 = './caltables/' + caltablebase + '.'+type+'_1'

                        tb.open(caltable0)
                        Time0  = tb.getcol('TIME').copy()
                        cgain0 = tb.getcol('CPARAM').copy()
                        ant0   = tb.getcol('ANTENNA1') .copy()
                        tb.close()

                        tb.open(caltable1)
                        Time1  = tb.getcol('TIME').copy()
                        cgain1 = tb.getcol('CPARAM').copy()
                        ant1   = tb.getcol('ANTENNA1') .copy()
                        tb.close()

                        if type == 'phase':
                            phase0_0 = np.angle(cgain0[0][0],deg=True)
                            phase0_1 = np.angle(cgain0[1][0],deg=True)
                            phase1   = np.angle(cgain1[0][0],deg=True)
                        elif type == 'amp_phase':
                            phase0_0 = np.abs(cgain0[0][0])
                            phase1   = np.abs(cgain1[0][0])


                        plt.close()
                        titlename = self.asdmname+' '+field+' spw:'+spw
                        plt.title(titlename)
                        plt.scatter((Time0-Time0[0])/60.,phase0_0,c='b',s=2)
                        if type == 'phase':
                            plt.scatter((Time0-Time0[0])/60.,phase0_1,c='b',s=2)
                        plt.scatter((Time1-Time1[0])/60.,phase1,c='r',s=1)
                        plt.xlabel('Time from the first integration [min]')
                        if type == 'phase':
                            plt.ylabel('Gain phase [deg]')
                        elif type == 'amp_phase':
                            plt.ylabel('Gain amplitude')
                        plt.savefig('./caltables/'+caltablebase+'.gainplot.'+type+'.png')
                        plt.savefig('./caltables/'+caltablebase+'.gainplot.'+type+'.pdf')
                        plt.close()

    # step5-7: uvfitting
    def uvfit_man(self,datacolumn='data',intent=None,write_residuals=False,savemodel=False,dryrun=False,meansub=False):

        if not dryrun:

            os.system('mkdir -p specdata')

            if intent == None:
                infile = './specdata/'+self.visname+'.split.'+self.field+'.spw_'+self.spw+'.dat'
            else:
                infile = './specdata/'+self.visname+'.split.'+self.field+'.spw_'+self.spw+'.'+intent+'.dat'

            from casatools import table
            #from scipy.optimize import least_squares
            tb = table()

            # freq
            tb.open('calibrated/'+self.visname+'.split.'+self.field+'.spw_'+self.spw+'/SPECTRAL_WINDOW')
            freq = tb.getcol('CHAN_FREQ').copy()
            freq = freq.reshape(freq.shape[0])
            tb.close()

            # spec
            tb.open('calibrated/'+self.visname+'.split.'+self.field+'.spw_'+self.spw,nomodify=False)
            data  = tb.getcol('DATA')
            model = np.zeros_like(data,dtype='complex')

            modeldata = np.loadtxt(infile)
            if modeldata.shape[0] <= 4:
                spec = np.zeros(1) + modeldata[1]

            else:
                if np.argsort(freq)[0] == np.argsort(modeldata[:,0])[0]:
                    spec = modeldata.copy()[:,1]

                elif np.argsort(freq)[0] == 0:
                    spec = modeldata.copy()[:,1][np.argsort(modeldata[:,0])]
                elif np.argsort(modeldata[:,0])[0] == 0:
                    spec = modeldata.copy()[:,1][np.argsort(freq)]

            if meansub:
                model = model + (np.mean(spec) + 0.*1j)
            else:
                for i in range(data.shape[2]):
                    model[0,:,i] = model[0,:,i] + spec.astype('complex')
                    model[1,:,i] = model[1,:,i] + spec.astype('complex')

            if savemodel:
                tb.putcol('MODEL_DATA',model.copy())

            if write_residuals:
                if datacolumn == 'data':
                    res = data.copy() - model.copy()
                elif datacolumn == 'corrected':
                    corr_data = tb.getcol('CORRECTED_DATA')
                    res = corr_data.copy() - model.copy()
                tb.putcol('CORRECTED_DATA', res)

            tb.flush()
            tb.close()

    # step5: uvmultifit & selfcal
    def uvfit_run(self,dryrun=False,plot=True):

        if not dryrun:
            for _field in self.fields:
                # selfcal by avaraged MS
                self.uvfit_splitQSO_allspw(field=_field,dryrun=dryrun)
                self.uvfit_createcol(dryrun=dryrun)
                self.uvfit_uvmultifit(write='',column='data',dryrun=dryrun,mfsfit=True,intent='noselfcal')
                self.uvfit_man(datacolumn='data',write_residuals=False,savemodel=True,intent='noselfcal',dryrun=dryrun,meansub=False)

                gaintable_p  = self.uvfit_gaincal(intent='phase_0',solint='int',gaintype='G',calmode='p',gaintable='',dryrun=dryrun)
                gaintable_ap = self.uvfit_gaincal(intent='amp_phase_0',solint='int',solnorm=True,gaintype='T',calmode='ap',gaintable=[gaintable_p],dryrun=dryrun)
                self.uvfit_applycal(gaintable=[gaintable_p,gaintable_ap],dryrun=dryrun)

                self.uvfit_uvmultifit(write='',column='corrected',intent='selfcal',dryrun=dryrun,mfsfit=True)
                self.uvfit_man(datacolumn='corrected',write_residuals=True,savemodel=True,intent='selfcal',dryrun=dryrun,meansub=False)

                gaintable_p1  = self.uvfit_gaincal(intent='phase_1',solint='int',gaintype='T',calmode='p',gaintable=[gaintable_p,gaintable_ap],dryrun=dryrun)
                gaintable_ap1 = self.uvfit_gaincal(intent='amp_phase_1',solint='int',solnorm=True,gaintype='T',calmode='ap',gaintable=[gaintable_p,gaintable_ap,gaintable_p1],dryrun=dryrun)

                # apply gaintable to each spw
                for _spw in self.spws:
                    self.uvfit_splitQSO(spw=_spw,field=_field,dryrun=dryrun)
                    self.uvfit_uvmultifit(write='',column='data',intent='noselfcal',dryrun=dryrun,mfsfit=False)
                    self.uvfit_applycal(gaintable=[gaintable_p,gaintable_ap],dryrun=dryrun)
                    self.uvfit_uvmultifit(write='',column='corrected',intent='selfcal',dryrun=dryrun,mfsfit=False)
                    if self.spacesave:
                        os.system('rm -rf calibrated/'+self.visname+'.split.'+self.field+'.spw_'+self.spw+'*')

            self.uvfit_gainplot(dryrun=(not plot),allspws=True,type='phase')
            self.uvfit_gainplot(dryrun=(not plot),allspws=True,type='amp_phase')

        self.writelog('step5:OK')

    # step6: continuum imaging
    def cont_imaging(self,statwtflag=False,dryrun=False):

        if not dryrun:

            for field in self.fields:
                os.system('rm -rf '+'./calibrated/concat.'+field+'.ms')
                vis = 'calibrated/'+self.visname+'.split.'+field+'.spw_all'

                if statwtflag:

                    kw_statwt = {
                        'vis':vis,
                        'combine':'',
                        'datacolumn':'corrected',
                        'flagbackup':False,
                        }

                    from casatasks import statwt
                    statwt(**kw_statwt)

                    visForimsg = kw_concat['concatvis']

                else:
                    visForimsg = vis

                kw_tclean = {
                    'vis':visForimsg, #vis,
                    'imagename':'./imsg/'+self.asdmname+'.'+field+'.residual.allspw.selfcal.mfs.briggs.robust_0.5.dirty',
                    'datacolumn':'corrected',
                    'imsize':self.imsize,
                    'cell':self.cell,
                    'weighting':'briggs',
                    'robust':0.5,
                    'deconvolver':'hogbom',
                    'gridder':'standard',
                    'specmode':'mfs',
                    'threshold':'0mJy',
                    'niter':0,
                    'nterms':2,
                    'interactive':False,
                    'pbcor':True,
                    'restoringbeam':'common',
                    }

                os.system('mkdir -p imsg')
                os.system('rm -rf '+kw_tclean['imagename']+'*')
                from casatasks import tclean, exportfits
                tclean(**kw_tclean)
                exportfits(kw_tclean['imagename']+'.image',kw_tclean['imagename']+'.image.fits')
                exportfits(kw_tclean['imagename']+'.image.pbcor',kw_tclean['imagename']+'.image.pbcor.fits')
                exportfits(kw_tclean['imagename']+'.psf',kw_tclean['imagename']+'.psf.fits')


                for ext in ['.image','.mask','.model','.image.pbcor','.psf','.residual','.pb','.sumwt']:
                    os.system('rm -rf '+kw_tclean['imagename']+ext)

        self.writelog('step6:OK')

    # step7: spacesaving
    def spacesaving(self,gzip=False,dryrun=False):

        if not dryrun:
            if self.spacesave:
                os.system('rm -rf *.last')
                os.system('rm -rf byspw')
                os.system('rm -rf tempfiles')
                os.system('rm -rf '+self.asdmname+'*')
                os.system('rm -rf '+self.projID)

                from casatasks import mstransform,listobs
                for field in  self.fields:
                    kw_mstransform = {
                        'vis':'calibrated/'+self.visname+'.split.'+field+'.spw_all',
                        'outputvis':'calibrated/'+self.visname+'.split.'+field+'.spw_all.selfcal.residual',
                        'datacolumn':'corrected',
                        'keepflags':True
                        }

                    os.system('rm -rf '+kw_mstransform['outputvis'])
                    mstransform(**kw_mstransform)
                    listobs(vis=kw_mstransform['outputvis'],listfile=kw_mstransform['outputvis']+'.listobs')
                    os.system('rm -rf '+kw_mstransform['vis'])
                    os.system('rm -rf '+kw_mstransform['vis']+'.listobs')

                try:
                    os.system('mkdir -p log')
                    os.system('mv ./casa-*.log ./log/')
                    os.system('cp ./calibrated/*.listobs ./log/')
                except:
                    print('ERRPR: copy casalog failed')

                os.system('mv ../log/'+self.tarfilename+'*.log ./log/')

                if gzip:
                    os.system('gzip -1 -v '+glob.glob('*.tar')[0])
                    os.system('rm -rf '+'calibrated.tar.gz')
                    os.system('tar -zcvf calibrated.tar.gz calibrated')
                    os.system('rm -rf ./calibrated')


        self.writelog('step7:OK')


    # step8: spectrum plot
    def specplot(self,dryrun=False):

        failflag = False

        if not dryrun:
            from astropy import stats
            import matplotlib.pyplot as plt

            for field in self.fields:
                for spw in self.spws:
                    try:
                        specfile = './specdata/'+self.visname+'.split.'+field+'.spw_'+spw+'.selfcal.dat'
                        data = np.loadtxt(specfile)
                        freq = data[:,0]/1.0e9 #GHz
                        spec = data[:,1] #Jy
                        spec_ma = stats.sigma_clip(spec,sigma=3.)

                        pp = np.ma.polyfit(freq,spec_ma,deg=1)
                        #cont = np.ma.median(spec_ma)
                        cont = pp[0]*freq+pp[1]
                        rms = np.ma.std(spec_ma/cont)
                        detect = np.ma.array(np.full_like(freq,np.ma.max(spec_ma/cont)+2.5*rms),mask=~spec_ma.mask)

                        ymax = np.max(spec/cont) + 5*rms
                        ymin = np.min(spec/cont) - 5*rms

                        plt.close()
                        plt.rcParams['font.family'] = 'Times New Roman'
                        plt.rcParams['mathtext.fontset'] = 'stix'
                        plt.rcParams["figure.dpi"] = 200
                        plt.rcParams["font.size"] = 20

                        plt.figure(figsize=[10,8])
                        #plt.gca().xaxis.set_major_formatter(plt.FormatStrFormatter('%.3f'))

                        plt.step(freq,spec/cont,where='mid',c='b',lw=1)
                        plt.plot(freq,detect,'r-',lw=5)
                        plt.xlabel('frequency [GHz]')
                        plt.ylabel('line/continuum')
                        titlename = self.asdmname + ': ' + field + ' spw' + spw
                        plt.title(titlename)
                        os.system('mkdir -p specplot')
                        plt.ylim(ymin,ymax)
                        plt.savefig('./specplot/'+self.asdmname + '.' + field + '.spw' + spw + '.pdf')
                        plt.savefig('./specplot/'+self.asdmname + '.' + field + '.spw' + spw + '.png')
                        plt.close()

                    except:
                        failflag = True

        if failflag:
            self.writelog('step8:Partially failed')
        else:
            self.writelog('step8:OK')



###
