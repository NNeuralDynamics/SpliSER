"""
SpliSER- Splice-site Strength Estimation from RNA-seq
"""
#Version 0.1.8 - 6th April 2022
version = "v0.1.8"
import sys
import timeit
import time
import subprocess
import argparse
import HTSeq
import pysam
import csv
from tqdm import tqdm
import re
from operator import truediv
from Gene_Site_Iter_Graph_v0_1_8 import Gene, Site, Iter, Graph
import numpy
from operator import add, truediv, mul, sub
import bisect
from ast import literal_eval


digit_pattern = re.compile(r'\D')

chrom_index = []
gene2D_array = []
site2D_array = []
Sites_2Darray = []
Genes = []
allChroms = []
allCounts = [] #stores the total number of evidencing reads for a given splice site, for a given sample.
allNames =[]
allSEs = [] #stores all the effiency values
allTitles = [] #stores all the names of files
geneCounter = 0


digit_pattern = re.compile(r'\D') # pattern, non-digit
char_pattern = re.compile(r'\d') # pattern, digit
sSite = None
QUERY_gene = None
NA_gene = Gene(chromosome = None,
					name = 'NA',
					leftPos = -1,
					rightPos = -1,
					readNums = None,
					samples = 1,
					strand = None,
					source = '')


def createGenes(annotation, aType, qGene):
	"""
	Create an array of Gene objects, based on the provided annotation.
	Expects Annotation file will have 5 columns
	0. Chromosome Identifier
	1. Strand
	2. Transcriptional start position
	3. Trsancriptional end position
	4. Gene Identifier

	For each line in the annotation decribing the 5' and 3' bounds of a gene, create a Gene object (see Gene_single.py) with those boundaries
	and append to an array of Genes.

	Assumes Gene list is sorted by ascending transcriptional start site position

	Parameters
	----------
	annotation : String
		The absolute file path of a GFF3/GTF annoation file
	qChrom : String
		The chromosome of interest, formatted how it appears in the annotation file (ie Chr1 for a TAIR10 GFF3 annoation file)
	qPos : int
		The genomic position of the splice site of interest
	qGene : str
		The Gene of interest

	Returns
	----------
	NA
	"""
	geneCounter = 0
	for line in HTSeq.GFF_Reader(annotation):
		if line.type == 'gene':
			GeneName = line.name
			chrom = line.iv.chrom
			GeneLeft = line.iv.start #lowest boundary position of gene in reference
			GeneRight = line.iv.end #highest boundary position of gene in reference
			strand = line.iv.strand


			if chrom not in chrom_index: #Add chromsome to index if not already there
				chrom_index.append(chrom)
				gene2D_array.append([])
			if qGene == 'All':
				geneCounter = geneCounter+1
				bisect.insort(gene2D_array[chrom_index.index(chrom)],Gene(chromosome = chrom,
												name = GeneName,
												leftPos = GeneLeft,
												rightPos = GeneRight,
												readNums = None,
												samples = 1,
												strand = strand,
												source = ''))
			elif GeneName == qGene:
				print('Query Gene found')
				global QUERY_gene
				QUERY_gene = Gene(chromosome = chrom,
							name = GeneName,
							leftPos = GeneLeft,
							rightPos = GeneRight,
							readNums = None,
							samples = 1,
							strand = strand,
							source = '')
				gene2D_array[chrom_index.index(chrom)].append(QUERY_gene)

	print(str(geneCounter)+" Genes created in "+str(len(chrom_index))+" bins")

def binary_gene_search(array, pos, strand, isStranded):
	'''
	Take an array and search for a Gene within it whose left and right bounds contain the given genomic position
	Return its position within the Array.

	Otherwise. If the Search is unsuccessful, retunrn position -1

	The overlap of some Genes cannot be perfect sorted. SO anytime we get stuck, we'll optimistically search three genes either side.
	Parameters
	----------
	array: An array of Gene Objects, specified by Gene_single
	pos: A genomic position query, expressed as an integer.
	'''
	length = int(len(array))
	if length == 0:
		return int(-1)

	idx = length // 2
	past_max = length
	past_min = 0
	last_idx = -1
	new_idx = idx
	stuck = False
	found = False
	while stuck == False and found == False:
		if int(pos) >= int(array[idx].getLeftPos()) and int(pos) <= int(array[idx].getRightPos()) and (strand == array[idx].getStrand() or isStranded==False or (strand != '+' and strand != '-') ): #if one site in junction lie within the given gene
			found = True
			break
		elif int(pos) >= int(array[idx].getRightPos()): #else if position is greater than gene boundaries, bisect above current pos
			new_idx = idx + ((past_max-idx)//2)
			past_min = idx
		elif int(pos) <= int(array[idx].getLeftPos()): #else if position is less than gene boundaries, bisect below current pos
			new_idx = idx - ((idx-past_min)//2)
			past_max = idx
			if idx == 1: ####Can't minus 0, so if we are still above our target position, we'll manually shift down to index 0
				new_idx = 0

		if idx != last_idx: #check if we are looping back and forth between two genes, if not then update tracker values
			last_idx = idx
			idx = new_idx
		else:
			stuck = True

	if found == False and stuck == True: # last ditch check up and downstream
		for i in range(-3,3):
			if idx+i >= 0 and idx+i < len(array)-1 and int(pos) >= int(array[idx+i].getLeftPos()) and int(pos) <= int(array[idx+i].getRightPos()) : #if one site in junction lie within the given gene
				#always consider gene strand, unless site strand is unknown.
				if strand == array[idx+i].getStrand() or isStranded==False or (strand != '+' and strand != '-'): #if the strand also matches, we've found it and can go ahead
					found = True
					stuck = False
					idx = idx+i

	if found == True and stuck == False:
		return int(idx)
	else:
		return int(-1)

def binary_site_search(array, pos, strand, isStranded):
	'''
	Take an array and search for a Site within it whose position matches the query genomic position
	Return its position within the Array
	Otherwise. If the Search is unsuccessful, retunrn position -1

	Parameters
	----------
	array: An array of Site Objects, specified by Gene_Site
	pos: A genomic position query, expressed as an integer.
	'''
	length = int(len(array))
	idx = length // 2
	past_max = length
	past_min = 0
	last_idx = -1
	new_idx = idx
	stuck = False
	found = False


	while stuck == False and found == False :

		if int(pos) == int(array[idx].getPos()): #if the site position matches
			if strand == array[idx].getStrand() or isStranded ==False or (strand != '+' and strand != '-'): #if the strand also matches, or if strand doesn't matter
				found = True
				break
			else: #the site we are looking for might have an opposite-strand (ie adjacent in the list)
				for a in [idx-1,idx+1]: #look up and downstream, then break the loop.
					if a >=0 and a <len(array) and int(pos) == int(array[a].getPos()) and (strand == array[a].getStrand() or isStranded ==False or (strand != '+' and strand != '-')):
						idx=a
						found=True
				break

		elif int(pos) >= int(array[idx].getPos()): #else if position is greater than the site, bisect above current pos
			new_idx = idx + ((past_max-idx)//2)
			past_min = idx
		elif int(pos) <= int(array[idx].getPos()): #else if position is less than the site, bisect below current pos
			new_idx = idx - ((idx-past_min)//2)
			past_max = idx
			if idx == 1: ####WOoooop
				new_idx = 0
		if idx != last_idx: #check if we are looping back and forth between two sites, if not then update tracker values
			last_idx = idx
			idx = new_idx
		else:
			stuck = True
	if found == True:
		return idx
	else:
		return -1

def findAlphaCounts(bedFile, qChrom, qGene, maxIntronSize, isStranded, sample=0, numsamples=1):
	"""
	Take each junction from the bed file, If it falls within a recorded Gene obect, record the  number of reads evidencing usage (alpha1 reads)of each splice site forming the junction.

	Parameters
	----------
	bedFile : String
		The absolute path to a junctions.bed file for a given alignment .
	sample : int
		The ordinal position of this sample, among all samples being assessed
	numsamples : int
		The total number of samples that will be assessed.
	"""
	print('Processing sample '+ str(int(sample)+1)+' out of '+str(numsamples))
	lineCounter = 0
	left_alphaCount = 0
	right_alphaCount = 0
	foundCounter = 0
	newCounter = 0
	duplicateCounter = 0
	assessedCounter = 0
	left_site_new = True
	right_site_new = True
	left_site_idx = -1
	right_site_idx = -1

	print(QUERY_gene)
	#check each junction in this bed file
	for line_idx, line in enumerate(open(bedFile, 'r')):
		#check for a header line
		values = str(line).split("\t")

		if len(values) == 12: # if not a header line
			lineCounter = lineCounter+1
			#values = str(line).split("\t")
			chrom = str(values[0])
			LinGene = False
			RinGene = False
			if chrom not in chrom_index: #Add chromsome to index if not already there (sometimes there are no annotated genes in a scaffold)
				chrom_index.append(chrom)
				site2D_array.append([])
				gene2D_array.append([])
			if qChrom == chrom or qChrom == "All":
				# find the index, which we'll use to specify the array we'll search.
				chrom_idx = chrom_index.index(str(chrom))
				strand = str(values[5])
				#identify the positions of each splice site
				flank = values[10].split(",")
				leftpos = int(values[1])+int(flank[0])
				rightpos = int(values[2])-int(flank[1])
				alpha = int(values[4])

				if qGene != 'All': # if we are chasing a particular gene
					lPosAdj = leftpos+maxIntronSize
					rPosAdj = rightpos-maxIntronSize
					#check if either site is within an intron length of the gene boundaries
					if lPosAdj >= QUERY_gene.getLeftPos() and leftpos <= QUERY_gene.getRightPos():
						LinGene = True
					if rPosAdj <= QUERY_gene.getRightPos() and rightpos >= QUERY_gene.getLeftPos():
						RinGene = True
				#if we are taking any gene, or if the sites are query-gene-associated
				if qGene =="All" or LinGene or RinGene:

					if len(site2D_array[chrom_idx])>0:
						left_site_idx = binary_site_search(site2D_array[chrom_idx],leftpos,strand,isStranded)
						right_site_idx = binary_site_search(site2D_array[chrom_idx],rightpos,strand,isStranded)

					else:
						left_site_idx = -1
						right_site_idx = -1

					assessedCounter += 2
					#FOR EACH SITE
					site_left = None
					site_right = None
					for num, site_info in enumerate([[leftpos,left_site_idx],[rightpos,right_site_idx]]):
						ss = None
						# if this is a new site
						if site_info[1] == -1:

							if num == 0:
								left_site_new = True
							if num == 1:
								right_site_new = True

							newCounter = newCounter + 1
							gene_idx = binary_gene_search(gene2D_array[chrom_idx], site_info[0], strand,isStranded)
							#Check if we found a gene for site
							if gene_idx >=0:
								gene = gene2D_array[chrom_idx][gene_idx]
								foundCounter +=1
							else:
								gene = NA_gene
							#Make the site
							ss = Site(
									chromosome = str(values[0]),
									pos = site_info[0],
									samples = numsamples,
									strand = strand,
									source = '',
									isStranded=isStranded
									)
							ss.setGene(gene)
							#add the site in it's ordered position
							#bisect.insort(site2D_array[chrom_idx],ss)
						else: #If the site has been recorded already
							if num == 0:
								left_site_new = False
								duplicateCounter += 1
							if num == 1:
								right_site_new = False
								duplicateCounter += 1
							ss = site2D_array[chrom_idx][site_info[1]]
						#record the alpha read counts
						ss.addAlphaCount(int(values[4]), sample)
						if num == 0: # if the left site
							site_left = ss
						else: #if the right site
							site_right = ss

					if left_site_new:
						bisect.insort(site2D_array[chrom_idx],site_left)
					if right_site_new:
						bisect.insort(site2D_array[chrom_idx],site_right)
						#add sites as partners for eachother, and record the shared alpha
					site_left.addPartner(site_right)
					site_left.addPartnerCount(site_right.getPos(), alpha, sample)
					site_right.addPartner(site_left)
					site_right.addPartnerCount(site_left.getPos(), alpha, sample)
	print("Sites assessed:\t"+str(assessedCounter))
	print("Sites found:\t\t\t"+str(newCounter))
	print("Sites assigned to a Gene:\t"+str(foundCounter))
	num =0
	for s in site2D_array:
		num = num + len(s)
	print("Sites:\t\t\t"+str(num))

def findCompetitorPos():
	for c_index, c in enumerate(chrom_index):
		for site in site2D_array[c_index]:
			sPos = site.getPos()
			for p in site.getPartners():
				for c in p.getPartners():
					cPos = c.getPos()
					if cPos != sPos:
						site.addCompetitorPos(cPos)

def check_strand(strandedType, SAMflag, siteStrand):
	'''
	Takes the flag element of a SAM and determines if that read originated from the same strand as the splice site
	'''
	if strandedType == "fr":
		if (SAMflag & 64) or not (SAMflag & 1): #if this is the first read, or this is not a paired read.

			if (SAMflag & 16): #and it was reverse strand
				readStrand = "-"
			else:
				readStrand = "+"
		else: #if this is the second read

			if (SAMflag & 16): #and it was reverse strand
				readStrand = "+"
			else:
				readStrand = "-"

	if strandedType == "rf":
		if (SAMflag & 64) or not (SAMflag & 1): #if this is the first read, or this is not a paired read.

			if (SAMflag & 16): #and it was reverse strand
				readStrand = "+"
			else:
				readStrand = "-"
		else: #if this is the second read

			if (SAMflag & 16): #and it was reverse strand
				readStrand = "-"
			else:
				readStrand = "+"

	return (readStrand == siteStrand)

def checkBam(bedFile, sSite, sample, isStranded, strandedType):
	#get the read counts for this IR junction
	#take list of competitors, and Partner positions
	#if we see a change from N->M or M->N at competitor and partner positions, then this is also a beta2 read - and we'll need to subtract from our beta2counts
	targetPos = sSite.getPos()
	#get list of partner and competitor positions
	competitors = sSite.getCompetitorPos()
	siteStrand = sSite.getStrand()

	partners = []
	for partner, counts in sSite.getPartnerCounts().items(): # getting this from partner counts instead of sSite.getPartners().. .getPos() so the funciton is compatible with process and combine commands
		partners.append(partner)

	#Call Samtools view to get all reads mapping across the splice site of interest.
	#bamview = subprocess.Popen(['samtools', 'view', str(bedFile), str(sSite.getChromosome())+':'+str(targetPos)+'-'+str((int(targetPos)+1))], stdout = subprocess.PIPE)
	#, stderr=subprocess.DEVNULL)
	 #--threads ', str(threads),' ', #Can Multithread, why not?
	#bamstream = bamview.stdout
	bamstream = bedFile.fetch(str(sSite.getChromosome()), targetPos, int(targetPos) + 1)

	for line in bamstream:#get the reads one by one
		#dline = line.decode('ascii')
		#values = str(dline).split('\t')
		values = line.to_string().split('\t')
		cPos = -1


		if len(values) >3: # if an actual SAM line
			leftBound= int(values[3]) #leftmost edge of read.
			if leftBound <= int(targetPos): #if the read crosses the splice site
				flag = int(values[1]) # get the SAM flag
				cigar = str(values[5])
				#preprocess cigar string
				digits = list(filter(None, digit_pattern.split(cigar)))
				chars = list(filter(None, char_pattern.split(cigar)))

				spliceSites = []
				partnerUsed = ""
				compSplicing = False

				alpha_read = False
				beta1_read = False
				compSplicing_read = False
				SimpleBeta2_flanking_read = False
				SimpleBeta2_beta1type_read = False
				SimpleBeta2_mutuallyExclusive_read = False
				currentPos = int(leftBound)

				for idx, d in enumerate(digits):

					case = chars[idx]
					if case in ['M', 'X', '=']:
						mappedRegion = True
						progression = True
					if case in ['N', 'D']:
						mappedRegion = False
						progression = True
					if case in ['I', 'S', 'H', 'P']:
						progression = False

					if progression:
						currentPos += int(d) #continuously increase left

						if int(targetPos) >= (currentPos -int(d)) and currentPos > int(targetPos) and currentPos > int(targetPos)+1: # if mapped region covers our site position AND 			the next position

							if mappedRegion:
								#beta1_read = True
								if isStranded:
									if check_strand(strandedType, flag, siteStrand): #if read belongs to same strand as site.
										beta1_read = True
								else: # if not a stranded analysis
									beta1_read = True
						#check if we see splicing between partner site and competitor site

						if case in ['N']:
							#calculate position of start and end sites
							lSite = currentPos - int(d)-1
							rSite = currentPos -1
							spliceSites.append(lSite)
							spliceSites.append(rSite)
							#check if this is an alpha read
							if lSite == targetPos:
								partnerUsed = rSite
								alpha_read = True
							if rSite == targetPos:
								partnerUsed = lSite
								alpha_read = True

							if rSite in competitors:
								if lSite in partners:
									compSplicing = True
									cPos = rSite
							if lSite in competitors:
								if rSite in partners:
									compSplicing = True
									cPos = lSite

							if compSplicing == True:
								if targetPos > lSite and targetPos < rSite: #in the case the target site has been spliced out
									SimpleBeta2_flanking_read = True
							#catch mutually-exclusive-type splicing.
							if alpha_read == False and compSplicing == False and targetPos > lSite and targetPos < rSite:
								if isStranded:
									if check_strand(strandedType, flag, siteStrand): #if read belongs to same strand as site.
										SimpleBeta2_mutuallyExclusive_read = True
								else:
									SimpleBeta2_mutuallyExclusive_read = True



				if beta1_read == True and compSplicing == True: # in case we see both non-usage of the site and competitive splicing
					SimpleBeta2_beta1type_read = True
				#Update Values for this Site - according to this read
				if (alpha_read == True and compSplicing == True): # in case we see usage of the site and 'competitive splicing' also
					#make a set of partners which were affected by the alpha beta read
					sP = set(partners)
					sS = set(spliceSites)
					sI = sP.intersection(sS)
					#update the AlphaBeta count for the non-targetsite using partners so we know to subract them later
					for p in sI:
						if p != partnerUsed: #don't count the alphaBeta read against the partner used by the target site
							sSite.addPartnerBeta2DoubleCount(p, 1, sample)

				elif SimpleBeta2_flanking_read == True: # if it's a Simple beta2 read count - we need to store which partner they came from, so the weight isn't applied to those reads

					if sys.argv[1] == 'combine' or sys.argv[1] == 'combineShallow':
						sSite.addBeta2SimpleCount(1, sample)
						#Add simple beta 2 reads if this is the combine command (this count is naive to bam/bed junction differences)
						if compSplicing == True:
							sSite.addCompetitorPos(cPos)
							#add competitor to site competitor list (redundant effort for 'process' subcommand, but needed for 'combine' subcommand)



				elif SimpleBeta2_mutuallyExclusive_read == True:
					sSite.addBeta2SimpleCount(1, sample)


				elif SimpleBeta2_beta1type_read == True:
					#make a set of partners which show Simple competitions
					sP = set(partners)
					sS = set(spliceSites)
					sI = sP.intersection(sS)
					#store a Simple count for the site, and record a double count read to buffer against the beta2 count later (which is blind to the fact this read is actually a Simplebeta2 read).
					for p in sI:
						sSite.addPartnerBeta2DoubleCount(p, 1, sample)
					sSite.addBeta2SimpleCount(1, sample)

					#add competitor to site competitor list (redundant effort for 'process' subcommand, but needed for 'combine' subcommand)
					if compSplicing == True:
						sSite.addCompetitorPos(cPos)

				elif beta1_read == True and SimpleBeta2_beta1type_read == False: # finally, if it's not SimpleBeta2, add read as a beta1 count
					sSite.addBeta1Count(1 , sample) # add counts for reads showing beta1 non-usage, and naught else


def trueDivCatchZero(array1, array2):
	"""
	Takes an Array (array1) and divides it by another array (array2), elementwise.
	Where an element of array2 is equal to zero, the resulting value will be Zero (rather than undefined).
	"""

	array3 = [0.0]*int(len(array1))
	for i, a2 in enumerate(array2):
		if a2 > 0.0:
			array3[i] = truediv(array1[i],a2)
	return array3

def subIntNoNeg(element1, element2):
	ans = int(element1) - int(element2)
	if ans >= 0:
		return ans
	else:
		return 0

def findBeta2Counts(site, numSamps):
	#find the beta2 counts for this site
	Partners= site.getPartners() # array of Site objects the current site is known to partner with
	PartnerCounts = site.getPartnerCounts() #dictionary of known partners and alpha counts shared with the target site
	beta2CrypticCounts = [0]*numSamps
	beta2CrypticWeighted = [0.00]*numSamps
	#total alpha reads of the target site
	TotalAlphas = site.getAlphaCounts()

	for i, pSite in enumerate(Partners):

		for competitorPos, counts in pSite.getPartnerCounts().items(): # getting this from partner counts instead of sSite.getPartners().. .getPos() so the funciton is compatible with process and combine commands
			#Get all beta2 simple counts where partner and competitor flank the target site.
			if pSite.getPos() > site.getPos() and int(competitorPos) < site.getPos():
				site.addBeta2SimpleCounts(counts)
				site.addPartnerBeta2DoubleCounts(pSite.getPos(),counts)
			elif pSite.getPos() < site.getPos() and int(competitorPos) > site.getPos():
				site.addBeta2SimpleCounts(counts)
				site.addPartnerBeta2DoubleCounts(pSite.getPos(),counts)

		#get the total alpha of that partner, for all samples
		pAlphas = pSite.getAlphaCounts()
		#get the alpha reads shared between this site and the partner
		pCounts = PartnerCounts[pSite.getPos()]
		#beta 2 reads are all alpha reads of that partner, minus those shared between partner site and the target site
		b2 = [x - y for x, y in zip(pAlphas, pCounts)]
		#See if the b2 reads for this partner contain any double counts (that we observed in checkBam)
		if pSite.getPos() in site.getPartnerBeta2DoubleCounts():
			doubleCounts = site.getPartnerBeta2DoubleCounts()[pSite.getPos()]
			#adjust for double-counter reads
			b2 = [subIntNoNeg(x,y) for x, y in zip(b2, doubleCounts)]
		#tally Cryptic beta 2 counts
		beta2CrypticCounts = [x + y for x, y in zip(beta2CrypticCounts, b2)]
		#calculate weights for the given partner
		pWeights = trueDivCatchZero(pCounts, TotalAlphas)
		#tally weighted beta2 counts
		for i in range(0,numSamps):
			b2[i] = b2[i]*pWeights[i]
		beta2CrypticWeighted = [x + y for x, y in zip(beta2CrypticWeighted, b2)]

	#update values for this site
	site.addBeta2CrypticCounts(beta2CrypticCounts)
	site.updateBeta2Weighted(beta2CrypticWeighted)


def calculateSSE(site, isbeta2Cryptic):

	alpha = list(site.getAlphaCounts())
	beta1 = site.getBeta1Counts()
	beta2Simple = site.getBeta2SimpleCounts()
	betas = [x + y for x, y in zip(beta1, beta2Simple)]

	if isbeta2Cryptic:
		beta2w = site.getBeta2WeightedCounts()
		betas = [x + y for x, y in zip(betas, beta2w)]

	denominator = [x + y for x, y in zip(alpha, betas)]

	site.setSSEs(trueDivCatchZero(list(alpha), list(denominator)))

def outputBedFile(outputPath,isbeta2Cryptic):
	outBed = open(outputPath+".SpliSER.tsv","w+")
	#Write the header line
	outBed.write("Region\tSite\tStrand\tGene\tSSE\talpha_count\tbeta1_count\tbeta2Simple_count\tbeta2Cryptic_count\tbeta2Cryptic_weighted\tPartners\tCompetitors\n")
	for c_index, c in enumerate(chrom_index):
		for site in site2D_array[c_index]:
			outBed.write(str(site.getChromosome())+"\t")
			outBed.write(str(site.getPos())+"\t")
			outBed.write(str(site.getStrand())+"\t")
			outBed.write(str(site.getGeneName())+"\t")
			outBed.write("{0:.3f}\t".format(site.getSSE(0)))
			outBed.write(str(site.getAlphaCount(0))+"\t")
			outBed.write(str(site.getBeta1Count(0))+"\t")
			outBed.write(str(site.getBeta2SimpleCount(0))+"\t")
			if isbeta2Cryptic:
				outBed.write(str(site.getBeta2CrypticCount(0))+"\t")
				outBed.write("{0:.5f}\t".format(site.getBeta2WeightedCount(0)))
			else:
				outBed.write("NA\t")
				outBed.write("NA\t")
			#outBed.write(str(site.getBeta2WeightedCount(0))+"\t")
			outBed.write(str(site.getPartnerCount(0))+"\t")
			outBed.write(str(site.getCompetitorPos())+"\n")
	outBed.close()

#Check if all elements of the list are equivalent.
def checkEqual2(list):
   return len(set(list)) <= 1

def makeSingleSpliceSite(iChrom, iPos, numSamples, iStrand, isStranded):
	return(Site(
				chromosome = iChrom,
				pos = iPos,
				samples = numSamples,
				strand = iStrand,
				source = '',
				isStranded=isStranded
				)
			)

def processSites(inBAM, qChrom, isStranded, strandedType, isbeta2Cryptic, sample=0, numsamples=1):
    print('Processing sample ' + str(int(sample) + 1) + ' out of ' + str(numsamples), time.asctime(), flush=True)
    for c in chrom_index:
        print("Processing region {}, n={}\t({})".format(c, len(site2D_array[chrom_index.index(c)]), time.asctime()),
              flush=True)
        if qChrom == c or qChrom == "All":
            for idx, site in enumerate(tqdm(site2D_array[chrom_index.index(c)], desc="checkBam")):
                # Go assign Beta 1 type reads from BAM file
                checkBam(inBAM, site, sample, isStranded, strandedType)
            # Once this is done for all sites, we can calculate SSE
            for idx, site in enumerate(tqdm(site2D_array[chrom_index.index(c)], desc="beta&sse")):
                findBeta2Counts(site, numsamples)
                calculateSSE(site, isbeta2Cryptic)


def process(inBAM, inBed, outputPath, qGene, qChrom, maxIntronSize, annotationFile, aType, isStranded, strandedType,
            isbeta2Cryptic):
    print('Processing')
    inBAM = pysam.Samfile(inBAM)
    if isStranded:
        print('Stranded Analysis {}'.format(strandedType))
    else:
        print('Unstranded Analysis')

    if annotationFile is not None:
        print('\n\nStep 0: Creating Genes from Annotation...', time.asctime(), flush=True)
        createGenes(annotationFile, aType, qGene)

    print(('\n\nPreparing Splice Site Arrays'), time.asctime(), flush=True)
    for x in chrom_index:
        site2D_array.append([])

    print('\n\nStep 1: Finding Splice Sites / Counting Alpha reads...', time.asctime(), flush=True)
    findAlphaCounts(inBed, qChrom, qGene, int(maxIntronSize),
                    isStranded)  # We apply theqGene filter here, where the splice site objects are made

    print('\n\nStep 2: Identifying Competitors of each splice site...', time.asctime(), flush=True)
    findCompetitorPos()

    print('\n\nStep 3: Finding Beta reads', time.asctime(), flush=True)
    processSites(inBAM, qChrom, isStranded, strandedType, isbeta2Cryptic)

    print('\nOutputting .tsv file', time.asctime(), flush=True)
    outputBedFile(outputPath, isbeta2Cryptic)
    inBAM.close()

def outputCombinedLines(outTSV, site, gene,isbeta2Cryptic):
	for idx, t in enumerate(allTitles): # for each sample
		outTSV.write(str(t)+"\t")
		outTSV.write(str(site.getChromosome())+"\t")
		outTSV.write(str(site.getPos())+"\t")
		outTSV.write(str(site.getStrand())+"\t")
		outTSV.write(gene+"\t")
		outTSV.write("{0:.3f}\t".format(site.getSSE(idx)))
		outTSV.write(str(site.getAlphaCount(idx))+"\t")
		outTSV.write(str(site.getBeta1Count(idx))+"\t")
		outTSV.write(str(site.getBeta2SimpleCount(idx))+"\t")
		if isbeta2Cryptic:
			outTSV.write(str(site.getBeta2CrypticCount(idx))+"\t")
			outTSV.write(str(site.getBeta2WeightedCount(idx))+"\t")
		else:
			outTSV.write("NA\t")
			outTSV.write("NA\t")
		outTSV.write(str(site.getPartnerCount(idx))+"\t")
		outTSV.write(str(site.getCompetitorPos())+"\n")





from tqdm import tqdm
import ast

def collectSites(samplesFile, outputPath):
    """
    Read each sample’s processed .SpliSER.tsv (column‑2 of samplesFile),
    extract every unique (chrom, pos, strand), determine the site type,
    merge classifications according to the rules, sort them, and write to outputPath
    with a header: Region, Site, Strand, SiteType.
    """
    # Dictionary to store sites: key=(chrom, pos, strand), value=set of classifications.
    site_dict = {}

    # Define the order in which we want to output the classifications.
    classification_order = ["exon_end", "exon_start", "both", "unknown"]

    def classify_site(pos, partners_str):
        """
        Classify a splice site given its position and Partners string.
        Returns one of:
          - "both": if both upstream and downstream partners exist.
          - "exon_end": if only downstream partners exist.
          - "exon_start": if only upstream partners exist.
          - "unknown": if no partners can be determined.
        """
        if not partners_str or partners_str.strip() == "":
            return "unknown"
        try:
            partners_dict = ast.literal_eval(partners_str)
        except Exception:
            return "unknown"

        if not isinstance(partners_dict, dict):
            return "unknown"

        try:
            partners = [int(key) for key in partners_dict.keys()]
        except Exception:
            partners = []

        upstream = [p for p in partners if p < pos]
        downstream = [p for p in partners if p > pos]

        if upstream and downstream:
            return "both"
        elif downstream:
            return "exon_end"
        elif upstream:
            return "exon_start"
        else:
            return "unknown"

    # Read all lines from samplesFile so that we know the total count.
    with open(samplesFile) as samples:
        sample_lines = samples.readlines()

    # Process each sample file listed in samplesFile using tqdm with a known total.
    for line in tqdm(sample_lines, desc="Processing sample files", total=len(sample_lines)):
        parts = line.rstrip().split("\t")
        if len(parts) < 3:
            continue  # Skip lines without enough columns.
        name, processed, bam = parts[0], parts[1], parts[2]
        
        # Read all lines from the processed file so we know the total count.
        with open(processed) as proc_file:
            proc_lines = proc_file.readlines()
        
        # Process each line of the processed file with tqdm
        for row in tqdm(proc_lines, desc=f"Processing {processed}", leave=False, total=len(proc_lines)):
            cols = row.rstrip().split("\t")
            if cols[0] == "Region":
                continue  # Skip header.
            chrom = cols[0]
            try:
                pos = int(cols[1])
            except ValueError:
                continue
            strand = cols[2]
            # Assume Partners is at index 10 (adjust if needed).
            partners_str = cols[10] if len(cols) > 10 else ""
            new_class = classify_site(pos, partners_str)
            key = (chrom, pos, strand)

            if key not in site_dict:
                site_dict[key] = set()
            # If a new classification is not "unknown", remove "unknown" if it exists.
            if new_class != "unknown" and "unknown" in site_dict[key]:
                site_dict[key].remove("unknown")
            site_dict[key].add(new_class)

    # Sort sites by chrom, pos, then strand.
    sorted_sites = sorted(site_dict.items(), key=lambda x: (x[0][0], x[0][1], x[0][2]))

    # Write the output file with a new SiteType column.
    with open(outputPath, "w") as out:
        out.write("Region\tSite\tStrand\tSiteType\n")
        for (chrom, pos, strand), class_set in sorted_sites:
            # Sort the classifications according to our defined order.
            sorted_classifications = sorted(class_set, key=lambda x: classification_order.index(x))
            site_type = ",".join(sorted_classifications)
            out.write(f"{chrom}\t{pos}\t{strand}\t{site_type}\n")





def fillSample(masterPath, processedPath, bamPath, outputPath, isStranded, strandedType, isbeta2Cryptic):
    """
    For a single sample: load master site list, copy existing counts from processedPath,
    fill missing sites by calling checkBam + calculateSSE on bamPath, and write complete TSV.
    """
    # Load master list: each row is (chrom, pos, strand, type)
    master = [(c, int(p), s) for c, p, s, t in csv.reader(open(masterPath), delimiter="\t") if c != "Region"]
    
    # Load existing sample data into a dict keyed by (chrom, pos, strand)
    existing = {}
    for row in csv.reader(open(processedPath), delimiter="\t"):
        if row[0] == "Region":
            continue
        existing[(row[0], int(row[1]), row[2])] = row

    # Open the BAM file using pysam
    bam = pysam.Samfile(bamPath)
    
    with open(outputPath, "w") as out:
        # Write header line
        out.write("Region\tSite\tStrand\tGene\tSSE\talpha_count\tbeta1_count\tbeta2Simple_count\tbeta2Cryptic_count\tbeta2_weighted\tPartners\tCompetitors\n")
        # Iterate over master list with a progress bar
        for chrom, pos, strand in tqdm(master, total=len(master), desc="Filling sample"):
            key = (chrom, pos, strand)
            if key in existing:
                out.write("\t".join(existing[key]) + "\n")
            else:
                # Create new splice site for missing site
                site = makeSingleSpliceSite(chrom, pos, 1, strand, isStranded)
                # Assign default gene so getGeneName() works properly
                site.setGene(NA_gene)
                # Process the BAM file for this site
                checkBam(bam, site, 0, isStranded, strandedType)
                calculateSSE(site, isbeta2Cryptic)
                partners = site.getPartnerCounts()
                geneName = site.getGeneName() if site.getGeneName() is not None else "NA"
                out.write(f"{chrom}\t{pos}\t{strand}\t{geneName}\t"
                          f"{site.getSSE(0):.3f}\t{site.getAlphaCount(0)}\t{site.getBeta1Count(0)}\t"
                          f"{site.getBeta2SimpleCount(0)}\t{site.getBeta2CrypticCount(0)}\t"
                          f"{site.getBeta2WeightedCount(0):.5f}\t{partners}\t{site.getCompetitorPos()}\n")
    bam.close()





def combine(samplesFile, outputPath,qGene, isStranded, strandedType, isbeta2Cryptic):
	print('Combining samples...')
	outTSV = open(outputPath+".combined.tsv", 'w+')
	outTSV.write("Sample\tRegion\tSite\tStrand\tGene\tSSE\talpha_count\tbeta1_count\tbeta2Simple_count\tbeta2Cryptic_count\tbeta2_weighted\tPartners\tCompetitors\n")
	#Process the input paths file
	samples = 0
	bedPaths = [] # stores the absolute path to each SpliSER.bed file
	BAMPaths = [] # stores the absolute path to each orginal bam file
	for line in open(samplesFile,'r'):
		values = line.split("\t")
		if len(values) ==3:
			samples +=1
			allTitles.append(values[0]) # record the sample moniker
			bedPaths.append(values[1]) # record the bed file paths
			BAMPaths.append(pysam.Samfile(values[2].rstrip())) # record BAM file paths
		elif len(values) >= 0:
			print(str(allTitles), str(bedPaths), str(BAMPaths))
			raise Exception('Samples File contains lines that do not have exactly 3 tab-separated columns')

	#First iterate through all files and make a list of all regions
	#make a graph of all relationships in the list
	allchroms = []
	beforeList = []
	afterList = []

	print('Establishing order of genomic regions.')
	for b in bedPaths: # for each processed file
		before = "-1" # set an arbitary initial region
		for idx, line in enumerate(open(b,'r')):
			if idx >0: # skip headers
				chrom = line.split("\t")[0] # get the genomic region
				if chrom != before: # if this is a new region
					beforeList.append(before)
					afterList.append(chrom)
					before = chrom
					if chrom not in allChroms:
						allChroms.insert(0,chrom)
	if not allChroms:
		print("No genomic regions found - EXITING")
		sys.exit()

	allChroms.insert(0,"-1")

	g = Graph(allChroms)
	for idx, b in enumerate(beforeList):
		g.addEdge(b, afterList[idx])

	chromsInOrder = g.topologicalSort()[1:] #droppping off the arbitrary first region again
	print("order of genomic regions deduced: {}".format(chromsInOrder))

	#Iterate bed files
	print('Iterating through files in parallel, to interleave lines and fill gaps.')
	iters = []
	for file in bedPaths: # make a bed file line generator for each bed file
		iters.append((open(file, 'r')))

	for iter in iters: #skip header line
		temp = next(iter, None)


	#initialise data structures needed for iterating along bed files
	currentVals = [['']*11]*samples #array to hold the current line for each bed file - 11 elements
	currentChromPos=0
	maxChromPos = len(chromsInOrder)-1
	currentChrom = chromsInOrder[currentChromPos] # The chromosome currently being assessed
	lowestPos = -1
	lowestPosStrand="?"
	assocGene = "" #use this to store the gene associated with the lowestPos
	chroms = ['']*samples
	iterGo = [True]*samples #initialise iterGo for each sample
	iterDone = [False]*samples


	#load up intial values
	count = 0
	filledCount = 0
	print('updated currentChrom to {}'.format(currentChrom))
	print("Combining data for site# "+str(count)+"...")
	while not(len(set(iterDone)) <=1 and iterDone[0] ==True): #Stop if all files are done iterating
		#refresh values
		sSite = None
		assocGene = ""
		partners = []
		competitors = []
		filledGap = False

		for idx, iter in enumerate(iters):
			#	print('processing Site: ',count,'file: ',idx)
			if iterDone[idx] ==False: #unless we have run out of lines for this file, get the values for this file
				#Get the next value for appropriate iters
				if iterGo[idx] == True:
					nextLine = next(iter,None)
					if nextLine is not None:
						currentVals[idx] = nextLine.rstrip().split("\t")
						#Update chroms seen this round
						chroms[idx] = currentVals[idx][0]
						iterGo[idx] = False #pause iterator until we know this value was used
					else: #if the iterator is done
						iterDone[idx] = True #recognise it is done
						chroms[idx] = None #set Chrom to None so we can ignore this file in our currentChrom equation

				#check position(if on curent chrom) - record if it's the lowest we've seen so far
				if chroms[idx] == currentChrom:
					pos = int(currentVals[idx][1])
					strand = currentVals[idx][2]
					if pos < lowestPos or lowestPos == -1 or (isStranded==True and pos==lowestPos and strand=="+"): #check if this is a new lowest position
						lowestPos = int(pos)
						lowestPosStrand = strand
						assocGene = currentVals[idx][3]

		#if we didn't exhaust all iterators at the start of this loop
		if not(len(set(iterDone)) <=1 and iterDone[0] ==True):
			#Create a Splice Site for lowestPos
			sSite = makeSingleSpliceSite(currentChrom, lowestPos, samples, '', isStranded)

			chromsCheck = [i for i in chroms if i == currentChrom]
			if len(chromsCheck)==0: # if we have exhausted the current region
				currentChromPos = currentChromPos + 1
				if currentChromPos > maxChromPos:
					currentChrom = None
				else:
					currentChrom = chromsInOrder[currentChromPos]
					count = 0
					print('updated currentChrom to {}'.format(currentChrom))
					print("Combining data for site# "+str(count)+"...")
			else: #if we are still adding new values
				#add values into SpliceSite Object
				for idx, vals in enumerate(currentVals):
						if vals[0] == currentChrom and int(vals[1]) == lowestPos and iterDone[idx] ==False and (isStranded==False or vals[2] == lowestPosStrand): #if this sample has values for the splice site (and if it's a stranded analysis we are looking at the same strand)
							iterGo[idx] = True #if we take values from this file, then we want to get a new line next time
							#add details in for splice sites
							sSite.setStrand(str(vals[2])) # set the strand for this site
							#sSite.setSSE(float(vals[4]),idx) # set SSE for this site
							sSite.addAlphaCount(int(vals[5]), idx) # add alpha Counts
							sSite.addBeta1Count(int(vals[6]), idx) # add beta1 Counts
							sSite.addBeta2SimpleCount(int(vals[7]), idx) # add beta2Simple Counts
							if vals[8]!= "NA":
								sSite.addBeta2CrypticCount(int(vals[8]), idx) # add beta2Cryptic Counts
								sSite.addBeta2Weighted(float(vals[9]), idx) # add beta2WeightedCounts
							#else do nothing, we don't need these values

							#recalculate SSE, since we might have used the isbeta2Cryptic flag differently in this step
							try:
								calculateSSE(sSite, isbeta2Cryptic)
							except:
								print("Could not recalculate SSE. You might be trying to use --beta2Cryptic flag without using it in the process step")
							#read partner counts as a dictionary and update the splice
							pCounts = literal_eval(str(vals[10]))
							for key, val in pCounts.items():
								partners.append(key)
								sSite.addPartnerCount(key, val ,idx)
							#read competitor positions as a list and add to the
							cPosList = literal_eval(str(vals[11]))
							for c in cPosList:
								competitors.append(c)
								sSite.addCompetitorPos(c)

						else: #if this sample doesn't have values for the spliceSite
							#find beta1 and beta2Simple counts for the site, using partners and competitors
							if qGene == 'All' or qGene == assocGene:
								filledGap = True
								checkBam(BAMPaths[idx], sSite, idx, isStranded, strandedType)
								sSite.setSSE(0.000,idx)
				#output lines for this splice site
				if qGene == 'All' or qGene == assocGene:
					outputCombinedLines(outTSV,sSite, assocGene,isbeta2Cryptic)
			#reset the lowestPos COUNTER
			lowestPos = -1
		if filledGap:
			filledCount += 1

		count += 1
		if count%10000 == 0:
			print("Combining data for site# "+str(count))
	#loop back
	print('Filled in Beta read counts for {} Sites not detected in some samples'.format(filledCount))


def combineShallow(samplesFile, outputPath, qGene, isStranded, minSamples, minReads, minSSE, strandedType, isbeta2Cryptic):
	print('Combining samples...')
	outTSV = open(outputPath+".combined.tsv", 'w+')
	outTSV.write("Sample\tRegion\tSite\tStrand\tGene\tSSE\talpha_count\tbeta1_count\tbeta2Simple_count\tbeta2Cryptic_count\tbeta2_weighted\tPartners\tCompetitors\n")
	#Process the input paths file
	samples = 0
	bedPaths = [] # stores the absolute path to each SpliSER.bed file
	BAMPaths = [] # stores the absolute path to each orginal bam file
	print('Reading in Samples File')
	for line in open(samplesFile,'r'):
		values = line.split("\t")
		if len(values) ==3:
			samples +=1
			allTitles.append(values[0]) # record the sample moniker
			bedPaths.append(values[1]) # record the bed file paths
			BAMPaths.append(values[2].rstrip()) # record BAM file paths

	print('Reading SpliSER processed files into memory')
	#instead of an iterator, make a list of a list of lines
	bedLines = []
	line_counter = []
	max_lines = []
	for file in bedPaths:
		line_list = []
		maxi = 0
		for idx,line in enumerate(open(file,"r")):
			if idx >0: # Skip headers

				if qGene != "All": #if we are prefiltering by qGene
					g = line.split("\t")[3]
					if g == qGene:
						maxi += 1
						line_list.append(line)
				else: # otherwise add as normal
					maxi += 1
					line_list.append(line)
		bedLines.append(line_list)
		line_counter.append(0)
		max_lines.append(maxi)

	#First iterate through all files and make a list of all regions
	#make a graph of all relationships in the list
	allchroms = []
	beforeList = []
	afterList = []

	print('Establishing order of genomic regions.')
	for b in bedPaths: # for each processed file
		before = "-1" # set an arbitary initial region
		for idx, line in enumerate(open(b,'r')):
			if idx >0: # skip headers
				chrom = line.split("\t")[0] # get the genomic region
				if chrom != before: # if this is a new region
					beforeList.append(before)
					afterList.append(chrom)
					before = chrom
					if chrom not in allChroms:
						allChroms.insert(0,chrom)
	if not allChroms:
		print("No genomic regions found - EXITING")
		sys.exit()

	allChroms.insert(0,"-1")
	#Build the graph of genomic regions
	g = Graph(allChroms)
	for idx, b in enumerate(beforeList):
		g.addEdge(b, afterList[idx])
	#Make a sorted list of genomic regions
	chromsInOrder = g.topologicalSort()[1:] #droppping off the arbitrary first region again
	print("order of genomic regions deduced: {}".format(chromsInOrder))
	#initialise data structures needed for iterating along bed files
	currentVals = [['']*11]*samples #array to hold the current line for each bed file - 11 columns
	currentChromPos=0
	maxChromPos = len(chromsInOrder)-1
	currentChrom = chromsInOrder[currentChromPos] # The chromosome currently being assessed
	lowestPos = -1
	lowestPosStrand="?"
	assocGene = "" #use this to store the gene associated with the lowestPos
	chroms = ['']*samples
	iterGo = [True]*samples #initialise iterGo for each sample
	iterDone = [False]*samples

	#load up intial values
	count = 0
	filledCount = 0
	print('updated currentChrom to {}'.format(currentChrom))
	print("Combining data for site# "+str(count)+"...")
	while not(len(set(iterDone)) <=1 and iterDone[0] ==True): #Stop if all files are done iterating
		#refresh values
		sSite = None
		assocGene = ""
		partners = []
		competitors = []
		filledGap = False
		posCounter = 0

		for idx, bed in enumerate(bedLines):
			#print('processing Site: ',count,'file: ',idx)
			if iterDone[idx] ==False: #unless we have run out of lines for this file, get the values for this file
				#Get the next linr from this bed file
				if iterGo[idx] == True:
					if line_counter[idx] < max_lines[idx]:
						nextLine = bed[line_counter[idx]]
						line_counter[idx] += 1
					else:
						nextLine = None

					if nextLine is not None:
						#get the values of the next line
						if qGene == 'All': #If we are assessing all sites - proceed as normal
							currentVals[idx] = nextLine.rstrip().split("\t")
							#Update chroms seen this round
							chroms[idx] = currentVals[idx][0]
							#pause iterator until we know this value was used
							iterGo[idx] = False
						else: #If we are looking for sites from a particular gene
							qGeneFound = False
							#check the gene associated with this site
							while qGeneFound == False and iterDone[idx] == False: #If the site we are looking at isn't from the qGene,  and the iterator isn't yet exhausted
								currentVals[idx] = nextLine.rstrip().split("\t") # get values for this site
								#print('{} {} {}'.format(currentVals[idx][0],currentVals[idx][1],currentVals[idx][3]))
								if currentVals[idx][3] == qGene: #If this is a site from qGene - proceed as normal
									qGeneFound = True
									chroms[idx] = currentVals[idx][0]
									iterGo[idx] = False
								elif iterGo[idx] == True: #else, if the iterator is still going
									if line_counter[idx] < max_lines[idx]:
										nextLine = bed[line_counter[idx]]
										line_counter[idx] += 1
									else:
										nextLine = None
									if nextLine is None: #if that is empty
										iterDone[idx] = True #recognise it is done
										chroms[idx] = None #set Chrom to None so we can ignore this file in our currentChrom equation
									#Otherwise the while loop will start again until we find something from qGene..


					else: #if the iterator is done
						iterDone[idx] = True #recognise it is done
						chroms[idx] = None #set Chrom to None so we can ignore this file in our currentChrom equation

				#check position(if on curent chrom) - record if it's the lowest we've seen so far

			if chroms[idx] == currentChrom:
				pos = int(currentVals[idx][1])
				strand = currentVals[idx][2]
				if pos < lowestPos or lowestPos == -1 or (isStranded==True and pos==lowestPos and strand != lowestPosStrand and strand=="+"):

					lowestPos = int(pos)
					lowestPosStrand = strand
					assocGene = currentVals[idx][3]
					#If our first encounter of a new lowestPos has more than 'minReads' reads, record that we've seen it
					reads = int(currentVals[idx][5])+ int(currentVals[idx][6])+int(currentVals[idx][7])
					sse = float(currentVals[idx][4])
					if reads >= minReads and sse >= minSSE:
						posCounter =  1
					else:
						posCounter = 0
				#elseagain, count up how many times it is seen with more than 'minReads' reads
				elif pos == lowestPos:
					reads = int(currentVals[idx][5])+ int(currentVals[idx][6])+int(currentVals[idx][7])
					sse = float(currentVals[idx][4]) #fixed 15Mar2022
					if reads >= minReads and sse >= minSSE:
						#If there are at least 10 reads, record that we've seen it
						posCounter = posCounter + 1

		#print("{} {} {} ".format(str(currentVals[0][1]),str(currentVals[1][1]),str(currentVals[2][1])))
		#print("{} {} {} ".format(str(iterGo[0]),str(iterGo[1]),str(iterGo[2])))
		#if we didn't exhaust all iterators at the start of this loop
		if not(len(set(iterDone)) <=1 and iterDone[0] ==True):



				#Create a Splice Site for lowestPos
				sSite = makeSingleSpliceSite(currentChrom, lowestPos, samples, '',isStranded)

				chromsCheck = [i for i in chroms if i == currentChrom]
				if len(chromsCheck)==0: # if we have exhausted the current region
					currentChromPos = currentChromPos + 1
					if currentChromPos > maxChromPos:
						currentChrom = None
					else:
						currentChrom = chromsInOrder[currentChromPos]
						count = 0
						print('updated currentChrom to {}'.format(currentChrom))
						print("Combining data for site# "+str(count)+"...")
				else: #if we are still adding new values
					#add values into SpliceSite Object
					if posCounter >= minSamples:  #If we have seen this site enough times for it to be worth processing.
						for idx, vals in enumerate(currentVals):
							if vals[0] == currentChrom and int(vals[1]) == lowestPos and iterDone[idx] ==False and (isStranded==False or vals[2] == lowestPosStrand): #if this sample has values for the splice site (and if it's a stranded analysis we are looking at the same strand)
								iterGo[idx] = True #if we take values from this file, then we want to get a new line next time
								#add details in for splice sites
								sSite.setStrand(str(vals[2])) # set the strand for this site
								#sSite.setSSE(float(vals[4]),idx) # set SSE for this site
								sSite.addAlphaCount(int(vals[5]), idx) # add alpha Counts
								sSite.addBeta1Count(int(vals[6]), idx) # add beta1 Counts
								sSite.addBeta2SimpleCount(int(vals[7]), idx) # add beta2Simple Counts
								if vals[8]!= "NA":
									sSite.addBeta2CrypticCount(int(vals[8]), idx) # add beta2Cryptic Counts
									sSite.addBeta2Weighted(float(vals[9]), idx) # add beta2WeightedCounts
								#Else do nothing, we don't need these values unless they've already been specified

								#recalculate SSE, since we might have used the isbeta2Cryptic flag differently in this step
								try:
									calculateSSE(sSite, isbeta2Cryptic)
								except:
									print("Could not recalculate SSE. You might be trying to use --beta2Cryptic flag without using it in the process step")

								#read partner counts as a dictionary and update the splice site
								pCounts = literal_eval(str(vals[10]))
								#print(pCounts, type(pCounts))
								for key, val in pCounts.items():
									partners.append(key)
									sSite.addPartnerCount(key, val ,idx)
								#read competitor positions as a list and add to the
								cPosList = literal_eval(str(vals[11]))
								for c in cPosList:
									competitors.append(c)
									sSite.addCompetitorPos(c)

							else: #if this sample doesn't have values for the spliceSite
								#find beta1 and beta2Simple counts for the site, using partners and competitors
								if qGene == 'All' or qGene == assocGene:
									filledGap = True
									checkBam(BAMPaths[idx], sSite, idx, isStranded, strandedType)
									sSite.setSSE(0.000,idx)
								#output lines for this splice site
						if qGene == 'All' or qGene == assocGene:
							outputCombinedLines(outTSV,sSite, assocGene,isbeta2Cryptic)
					else:	# If there were not enough samples recording the splice site to pass minSamples
						print("Skipped site {} for insufficient evidence, only {} samples with Site using minimum reads".format(lowestPos,posCounter))
						#print(lowestPos)
						#print("{} {} {} ".format(str(iterGo[0]),str(iterGo[1]),str(iterGo[2])))
						for idx, vals in enumerate(currentVals):
							if iterDone[idx] == False and int(currentVals[idx][1]) == lowestPos:
								iterGo[idx] = True #we want to get a new line next time
				#reset the lowestPos COUNTER
				lowestPos = -1

		if filledGap:
			filledCount += 1

		count += 1
		if count%10000 == 0:
			print("Combining data for site# "+str(count)+"...")
	#loop back
	print('Filled in Beta read counts for {} Sites not detected in some samples'.format(filledCount))

def DiffSpliSER_output(samplesFile,combinedFile, outputPath, minReads, qGene):

	outDiff = open(outputPath+str(qGene)+".DiffSpliSER.tsv", "w+")
	correct = True
	fileFinished = False
	#record the samples we're assessing
	samples = 0
	for line in open(samplesFile,'r'):
		values = line.split("\t")
		if len(values) ==3:
			samples +=1
			allTitles.append(values[0]) # record the sample moniker

	#print the headerLine
	outDiff.write("Region\tSite\tStrand\tGene")
	for t in allTitles:
		outDiff.write("\t"+str(t)+"_alpha")
		outDiff.write("\t"+str(t)+"_beta")
		outDiff.write("\t"+str(t)+"_SSE")
	outDiff.write("\n")

	#make an iterator for the combined file
	comboFile = open(combinedFile, 'r')
	#skip the header
	#comboFile.next()
	nextLine = next(comboFile,None)

	while not fileFinished: #go until the file is exhausted
		currentVals = []
		for idx, t in enumerate(allTitles):
			#Skip the header
			nextLine = next(comboFile,None)
			if nextLine is not None:
				currentVals.append(nextLine.rstrip().split("\t")) #store an array of values for each sample
				if currentVals[idx] == t: #check that each title matches up with the line we've just extracted
					correct = True
			else:
				fileFinished = True
		#if we didnt hit the end of the file, output some valuuuues
		if not fileFinished:
			if not correct:
				print("Samples aren\'t match up, please check there are no missing lines in your combined file, or missing lines in your samples file" )
				break

			outDiff.write(str(currentVals[0][1])+"\t"+str(currentVals[0][2])+"\t"+str(currentVals[0][3])+"\t"+str(currentVals[0][4])) #write the region, splice site, and gene
			for idx, t in enumerate(allTitles):
				t_alpha = int(currentVals[idx][6])# get alpha Values
				t_beta = float(currentVals[idx][7])+float(currentVals[idx][8]) # add beta1 and beta2Simple
				if currentVals[idx][10] != "NA":
					t_WeightedCrypticBeta = float(currentVals[idx][10])
				else:
					t_WeightedCrypticBeta =0

				t_SSE = float(currentVals[idx][5])
				if t_alpha+t_beta >= minReads: # if this sample passes the minimum read count for this site

					t_beta = t_beta+t_WeightedCrypticBeta
					outDiff.write("\t"+str(t_alpha)+"\t"+"{0:.2f}".format(t_beta)+"\t"+"{0:.2f}".format(t_SSE))
				else:
					outDiff.write("\tNA\tNA\tNA")
			outDiff.write("\n")

def GWAS_output(samplesFile,combinedFile, outputPath, minReads, qGene, minSamples):
	print(qGene)
	fileFinished = False
	correct = True
	#record the samples we're assessing
	samples = 0
	for line in open(samplesFile,'r'):
		samples +=1
		values = line.split("\t")
		allTitles.append(values[0]) # record the sample moniker

	#open the datafile
	comboFile = open(combinedFile, 'r')
	#skip the header
	#comboFile.next()
	nextLine = next(comboFile,None)
	while not fileFinished: #go until the file is exhausted
		currentVals = []
		for idx, t in enumerate(allTitles):
			nextLine = next(comboFile,None)
			if nextLine is not None:
				currentVals.append(nextLine.rstrip().split("\t")) #store an array of values for each sample
				if currentVals[idx] == t: #check that each title matches up with the line wes've just extracted
					correct = True
			else:
				fileFinished = True
		#if we didnt hit the end of the file, output some valuuuues
		if not fileFinished:
			if not correct:
				print("Samples aren\'t match up, please check there are no missing lines in your combined file, or missing lines in your samples file" )
				break

			currentGene = str(currentVals[0][4])
			currentSite = str(currentVals[0][2])
			bufferString = ''
			samplesPassing = 0
			if qGene == currentGene or qGene == 'All':
				filtered = open(str(outputPath+currentGene+"_"+currentSite+"_filtered.log"),'w+') # otherwise write into a filter log file specific for this gene
				for idx, t in enumerate(allTitles):
					t_alpha = int(currentVals[idx][6])# get alpha Values
					t_beta = float(currentVals[idx][7])+float(currentVals[idx][8]) # add beta1 and beta2Simple values
					if t_alpha+t_beta >= minReads: # if this sample passes the minimum read count for this site
						samplesPassing +=1
						bufferString = bufferString+str(currentVals[idx][0])+"\t"+str(currentVals[idx][5])+"\n" #store sample name and SSE in buffer
					else:
						filtered.write(str(t)+" did not pass minReads for "+currentSite+"\n")
				if samplesPassing >= minSamples:
					out = open(outputPath+currentGene+"_"+currentSite+".tsv","w+") #open a file named after the splice site
					#out.write("Sample\tSSE\n")#Write in a header
					out.write(bufferString) # write stored info
					out.close()
				else:
					filtered.write("Site: "+currentSite+" minSamples not met - venting buffer\n")
					filtered.write(bufferString+"\n")

				filtered.close()

def output(outputType, samplesFile,combinedFile, outputPath, minReads, qGene, minSamples):
	if outputType == 'DiffSpliSER':
		DiffSpliSER_output(samplesFile,combinedFile, outputPath, minReads, qGene)
	if outputType == 'GWAS':
		GWAS_output(samplesFile,combinedFile, outputPath, minReads, qGene, minSamples)

#Main Method
if __name__ == "__main__":
	print("\nSpliSER "+version+" SKB LAB\n")
	# this won't be run when imported
	start = timeit.default_timer()

	#Parse arguments form the command line
	parser = argparse.ArgumentParser(description="SpiSER - Splice Site Strength Estimates from RNA-seq")
	subparsers = parser.add_subparsers(dest="command")
	#Parser for arguments when user calls command 'process'
	parser_process = subparsers.add_parser('process')
	parser_process.add_argument('-B', '--BAMFile', dest='inBAM', help="The mapped RNA-seq file in BAM format", required=True)
	parser_process.add_argument('-b', '--bedFile', dest='inBed', help="The Tophat-style splice junction bed file", required=True)
	parser_process.add_argument('-o', '--outputPath', dest='outputPath', help="Absolute path, including file prefix where SpliSER will write the .SpliSER.tsv file", required=True)
	parser_process.add_argument('-A', '--annotationFile', dest='annotationFile', help="optional: gff3 or gtf file matching the reference genome used for alignment", required=False)
	parser_process.add_argument('-t', '--annotationType', dest='aType', nargs='?', default='gene', type=str, help="optional: The feture to be extracted from the annotation file - default: gene", required=False)
	parser_process.add_argument('-c', '--chromosome', dest='qChrom', nargs='?', default='All', type=str,help="optional: limit SpliSER to one chromosome/scaffold -  default: All", required=False)
	parser_process.add_argument('-g', '--gene', dest='qGene', nargs='?', default='All', type=str, help="optional:Limit SpliSER to splice sites falling in a single locus (requires --chromosome and --annotationFile and --maxIntronSize)", required=False)
	parser_process.add_argument('-m', '--maxIntronSize', dest='maxIntronSize', nargs='?', default=0, type=int, required=False, help="optional: required if passing the --gene parameter, the max intron size used in aligning the bam file")
	#parser_process.add_argument('-S', '--isStranded', dest='isStranded', nargs='?', default=False, type=bool, required=False, help="optional: True/False Perform a strand-aware analysis - default: False")
	parser_process.add_argument('--isStranded', dest='isStranded', default=False, action='store_true')
	parser_process.add_argument('-s', '--strandedType', dest='strandedType', nargs='?', type=str, required=False, help="optional: Strand specificity of RNA library preparation, where \"rf\" is first-strand/RF and \"fr\" is second-strand/FR - default : fr")
	parser_process.add_argument('--beta2Cryptic', dest='isbeta2Cryptic', default=False, action='store_true', help="optional: Calculate SSE of sites taking into account the weighted utilisation of competing splice sites as indirect evidence of site non-utilisation (Legacy).")
	#Parser for arguments when user calls command 'combine'
	parser_combine = subparsers.add_parser('combine')
	parser_combine.add_argument('-S', '--samplesFile', dest='samplesFile', required=True, help="A three-column .tsv file, each line containing a sample name, the absolute path to a processed .SpliSER.tsv file input, and the absolute path to the original bam file")
	parser_combine.add_argument('-o', '--outputPath', dest='outputPath', required=True, help="Absolute path to a folder, including file_prefix where SpliSER will write the output .tsv file")
	parser_combine.add_argument('-g', '--gene', dest='qGene', nargs='?', default='All', type=str, help="optional:Limit SpliSER to splice sites falling in a single locus - default All", required=False)
	parser_combine.add_argument('--isStranded', dest='isStranded', default=False, action='store_true')
	parser_combine.add_argument('-s', '--strandedType', dest='strandedType', nargs='?', default="fr", type=str, required=False, help="optional: Strand specificity of RNA library preparation, where \"rf\" is first-strand/RF and \"fr\" is second-strand/FR - default : fr")
	parser_combine.add_argument('--beta2Cryptic', dest='isbeta2Cryptic', default=False, action='store_true', help="optional: Calculate SSE of sites taking into account the weighted utilisation of competing splice sites as indirect evidence of site non-utilisation (Legacy).")

	parser_combineShallow = subparsers.add_parser('combineShallow')
	parser_combineShallow.add_argument('-S', '--samplesFile', dest='samplesFile', required=True, help="A three-column .tsv file, each line containing a sample name, the absolute path to a processed .SpliSER.tsv file input, and the absolute path to the original bam file")
	parser_combineShallow.add_argument('-g', '--gene', dest='qGene', nargs='?', default='All', type=str, help="optional:Limit SpliSER to splice sites falling in a single locus - default All", required=False)
	parser_combineShallow.add_argument('-o', '--outputPath', dest='outputPath', required=True, help="Absolute path to a folder, including file_prefix where SpliSER will write the output .tsv file")
	parser_combineShallow.add_argument('--isStranded', dest='isStranded', default=False, action='store_true')
	parser_combineShallow.add_argument('-m', '--minSamples', dest='minSamples', required=False, nargs='?', default=0, type=int, help="For optional filtering: For any given splice site, the minimum number of samples passing the --minReads filter in order for a site to be kept in the analysis (Raising this value increases speed of combineShallow step)")
	parser_combineShallow.add_argument('-r', '--minReads', dest='minReads',required=False, nargs='?', default=10, type=int, help="For optional filtering: The minimum number of reads giving evidence for a splice site needed for downstream analyses - default: 10")
	parser_combineShallow.add_argument('-e','--minSSE', dest='minSSE',required=False, nargs='?', default=0.00, type=float, help="For optional filtering: The minimum SSE of a site for a given sample, for it to be considered in the --minSamples filter - default: 0.00")
	parser_combineShallow.add_argument('-s', '--strandedType', dest='strandedType', nargs='?', type=str, required=False, help="optional: Strand specificity of RNA library preparation, where \"rf\" is first-strand/RF and \"fr\" is second-strand/FR - default : fr")
	parser_combineShallow.add_argument('--beta2Cryptic', dest='isbeta2Cryptic', default=False, action='store_true', help="optional: Calculate SSE of sites taking into account the weighted utilisation of competing splice sites as indirect evidence of site non-utilisation (Legacy).")

	parser_output = subparsers.add_parser('output')
	parser_output.add_argument('-S', '--samplesFile', dest='samplesFile', required=True, help="the three-column .tsv file you used to combine the samples in the previous step")
	parser_output.add_argument('-C', '--combinedFile', dest='combinedFile', required=True, help="a SpliSER .combined.tsv file containing the splice site information for each sample")
	parser_output.add_argument('-t', '--outputType', dest='outputType', required = True, help="Type of output file: -t DiffSpliSER will output a file ready for differential splicing analysis. -t GWAS will output an SSE phenotype file for each Splice Site (writes to outputPath folder, ignoring file prefix)")
	parser_output.add_argument('-o', '--outputPath', dest='outputPath', required=True, help="Absolute path to an output folder(ie ending in a slash), iff using -t DiffSpliSER also provide a file_prefix where SpliSER will write the output .tsv file")
	parser_output.add_argument('-r', '--minReads', dest='minReads',required=False, nargs='?', default=10, type=int, help="The minimum number of reads giving evidence for a splice site in a given sample, below which SpliSER will report NA - default: 10")
	parser_output.add_argument('-g', '--gene', dest='qGene', required=False, nargs='?', default='All', type=str, help="optional:Limit SpliSER to splice sites falling in a single locus")
	parser_output.add_argument('-m', '--minSamples', dest='minSamples', required=False, nargs='?', default=50, type=int, help="optional: when using --outputType GWAS: the minimum number of samples passing the read filter for a splice site file to be written")

	# ——— New “collectSites” subcommand ———
	parser_collect = subparsers.add_parser('collectSites')
	parser_collect.add_argument('-S','--samplesFile', dest='samplesFile', required=True,
								help="Three‑column TSV (sample name, SpliSER.tsv, BAM) to extract all unique splice sites")
	parser_collect.add_argument('-o','--outputPath', dest='outputPath', required=True,
								help="Path to write master site list (TSV)")
	
	# ——— New “fillSample” subcommand ———
	parser_fill = subparsers.add_parser('fillSample')
	parser_fill.add_argument('-m','--masterSites', dest='masterPath', required=True,
							 help="Path to master site list created by collectSites")
	parser_fill.add_argument('-i','--inputTSV', dest='processedPath', required=True,
							 help="This sample’s pre‑processed SpliSER.tsv")
	parser_fill.add_argument('-B','--BAMFile', dest='bamPath', required=True,
							 help="This sample’s filtered BAM")
	parser_fill.add_argument('-o','--outputPath', dest='outputPath', required=True,
							 help="Path to write this sample’s completed TSV")
	parser_fill.add_argument('--isStranded', dest='isStranded', action='store_true', default=False)
	parser_fill.add_argument('-s','--strandedType', dest='strandedType', default="fr", help="fr or rf")
	parser_fill.add_argument('--beta2Cryptic', dest='isbeta2Cryptic', action='store_true', default=False)

        
	#Parse arguments
	kwargs = vars(parser.parse_args())
	command = kwargs.pop('command')

	#in process command, --g requires --A
	if command == 'process' and (kwargs.get('qGene') != "All") and ((kwargs.get('annotationFile') is None) or (kwargs.get('maxIntronSize') is None)):
		print(kwargs.get('qGene'))
		print(kwargs.get('annotationFile'))
		parser.error("--gene requires --annotationFile and --maxIntronSize")
	elif (command == 'process' or command == 'combine' or command =='combineShallow') and (kwargs.get('isStranded') is True) and (kwargs.get('strandedType') is None):
		parser.error("--isStranded requires parameter --strandedType/-s as fr or rf")
	else: #otherwise
		# call appropriate functions
		globals()[command](**kwargs)

	stop = timeit.default_timer()
	print("Total runtime (s): \t"+ str(stop - start))
#EOF
